from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from decimal import Decimal
from typing import Any, Mapping, Sequence

from cbr_trading.execution import (
    TickSizeChangeDetector,
    TickSizeWatch,
)
from cbr_trading.live.market import PolymarketMarketGateway
from cbr_trading.live.market_channel import PolymarketMarketChannel
from cbr_trading.live.order_group_repository import (
    SqlAlchemyOrderGroupRepository,
)
from cbr_trading.live.supervision_runtime import OrderSupervisionRuntime
from cbr_trading.mstr_btc import mstr_jul21_27_market_bindings
from cbr_trading.orchestration import SqlAlchemyResolutionProfileStore
from cbr_trading.resolution_hosted import (
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.secret_guard import redact_exception


_CONFIRMATION = "PRODUCTION_MSTR_SUPERVISION_NO_SUBMIT"
_OUTCOMES = ("YES", "NO")
_ALLOWED_TICKS = frozenset(
    {Decimal("0.01"), Decimal("0.001")}
)


class _NoSubmitSupervisor:
    def __init__(self, *, repository: Any | None = None):
        self._repository = repository
        self.tick_events = 0
        self.reconciliations = 0
        self.closed = False

    def on_tick_size_change(self, _event: object) -> tuple[()]:
        self.tick_events += 1
        return ()

    def reconcile(self) -> tuple[()]:
        self.reconciliations += 1
        return ()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._repository is not None:
            self._repository.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload: dict[str, Any] | None = None
    failure: str | None = None
    repository: SqlAlchemyOrderGroupRepository | None = None
    profile_store: SqlAlchemyResolutionProfileStore | None = None
    runtime: OrderSupervisionRuntime | None = None
    try:
        settings = HostedResolutionSettings.from_env(os.environ)
        guard_error = _guard_error(
            args=args,
            settings=settings,
            environ=os.environ,
        )
        if guard_error is not None:
            raise ValueError(guard_error)

        profile_store = SqlAlchemyResolutionProfileStore(
            database_url=settings.database_url,
        )
        profile_store.ensure_ready()
        if profile_store.load_enabled():
            raise RuntimeError(
                "no-submit supervision smoke requires all profiles disabled"
            )

        repository = SqlAlchemyOrderGroupRepository(
            database_url=settings.database_url,
        )
        repository.ensure_ready()
        if repository.has_pending_supervision_work():
            raise RuntimeError(
                "pending supervision work exists before the smoke"
            )

        runtime_supervisor = _NoSubmitSupervisor(
            repository=repository,
        )
        runtime = OrderSupervisionRuntime(
            repository=repository,
            supervisor=runtime_supervisor,
            watch_refresh_interval=0.1,
            reconciliation_interval=0.1,
        )
        runtime.start()
        time.sleep(0.35)
        if not runtime.running:
            raise RuntimeError("supervision runtime stopped unexpectedly")
        if runtime.active_watch_count != 0:
            raise RuntimeError(
                "disabled profiles produced active supervision watches"
            )
        runtime.stop()
        runtime = None
        repository = None

        snapshots = _load_public_snapshots()
        watches = _watches_for_snapshots(snapshots)
        channel_result = asyncio.run(
            _smoke_market_channel(
                watches,
                duration=args.duration,
            )
        )
        payload = {
            "ok": True,
            "mode": "production_mstr_supervision_no_submit",
            "database_target": settings.database_target,
            "profile_count": 0,
            "market_outcome_count": len(snapshots),
            "watch_count": len(watches),
            "runtime_started": True,
            "runtime_reconciled": (
                runtime_supervisor.reconciliations > 0
            ),
            "market_channel_required": bool(watches),
            "market_channel_connected": channel_result[
                "connected"
            ],
            "tick_event_count": channel_result["tick_event_count"],
            "order_inspection_called": False,
            "order_cancellation_called": False,
            "order_submission_called": False,
            "trading_secrets_mounted": False,
        }
    except Exception as exc:
        failure = redact_exception(exc)
    finally:
        if runtime is not None:
            try:
                runtime.stop()
            except Exception:
                if failure is None:
                    failure = "RuntimeError"
        elif repository is not None:
            repository.close()
        if profile_store is not None:
            profile_store.close()

    if failure is not None or payload is None:
        _print_json(
            {
                "ok": False,
                "mode": "production_mstr_supervision_no_submit",
                "order_submission_called": False,
                "error": failure or "smoke produced no result",
            },
            stream=sys.stderr,
        )
        return 5

    _print_json(payload, stream=sys.stdout)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check the production supervision schema, background runtime, "
            "public books, and market WebSocket without mounting trading "
            "secrets or calling an authenticated order endpoint."
        )
    )
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"Required literal confirmation: {_CONFIRMATION}.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=3.0,
        help="Seconds for which the public market channel must stay alive.",
    )
    return parser


def _guard_error(
    *,
    args: argparse.Namespace,
    settings: HostedResolutionSettings,
    environ: Mapping[str, str],
) -> str | None:
    if args.confirm != _CONFIRMATION:
        return "explicit no-submit supervision confirmation is required"
    if (
        not math.isfinite(args.duration)
        or args.duration < 1
        or args.duration > 15
    ):
        return "duration must be between 1 and 15 seconds"
    if str(environ.get("CODEXPOLY_ENVIRONMENT") or "").strip().lower() != (
        "production"
    ):
        return "CODEXPOLY_ENVIRONMENT must be production"
    if settings.mode is not HostedResolutionMode.SHADOW:
        return "no-submit supervision smoke requires shadow mode"
    if settings.supervision_enabled:
        return "no-submit supervision smoke requires supervision disabled"
    if _enabled(environ.get("CBR_LIVE_TRADING_ENABLED")):
        return "no-submit supervision smoke forbids live trading"
    if any(
        str(environ.get(name) or "").strip()
        for name in (
            "ACCOUNTS_MASTER_KEY",
            "ACCOUNTS_MASTER_KEY_FILE",
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED",
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_FILE",
        )
    ):
        return "no-submit supervision smoke forbids trading secret mounts"
    if not settings.database_url:
        return "production database is not configured"
    try:
        from sqlalchemy.engine import make_url

        database = make_url(settings.database_url)
    except Exception:
        return "production database configuration is invalid"
    if (
        settings.database_target != "server_int"
        or str(database.host or "").casefold() != "postgres"
        or str(database.database or "") != "codexpoly"
        or str(database.username or "") != "codexpoly_app"
    ):
        return "smoke requires the internal production database"
    return None


def _load_public_snapshots() -> tuple[Any, ...]:
    gateway = PolymarketMarketGateway()
    return tuple(
        gateway.load_snapshot(
            condition_id=binding.condition_id,
            outcome=outcome,
        )
        for binding in mstr_jul21_27_market_bindings()
        for outcome in _OUTCOMES
    )


def _watches_for_snapshots(
    snapshots: Sequence[Any],
) -> tuple[TickSizeWatch, ...]:
    rows = tuple(snapshots)
    if len(rows) != 6:
        raise RuntimeError("expected six MSTR market outcomes")
    if any(
        Decimal(str(snapshot.tick_size)) not in _ALLOWED_TICKS
        for snapshot in rows
    ):
        raise RuntimeError("an MSTR market has an unsupported tick size")
    token_ids = [str(snapshot.token_id or "").strip() for snapshot in rows]
    if any(not token_id for token_id in token_ids):
        raise RuntimeError("an MSTR market outcome has no asset identity")
    if len(token_ids) != len(set(token_ids)):
        raise RuntimeError("MSTR market outcome assets are not unique")
    return tuple(
        TickSizeWatch(
            asset_id=str(snapshot.token_id),
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
        )
        for snapshot in rows
        if Decimal(str(snapshot.tick_size)) == Decimal("0.01")
    )


async def _smoke_market_channel(
    watches: Sequence[TickSizeWatch],
    *,
    duration: float,
    channel_factory: Any = PolymarketMarketChannel,
) -> dict[str, Any]:
    watch_rows = tuple(watches)
    if not watch_rows:
        return {"connected": True, "tick_event_count": 0}
    supervisor = _NoSubmitSupervisor()
    detector = TickSizeChangeDetector(watch_rows)
    channel = channel_factory(
        detector=detector,
        supervisor=supervisor,
    )
    task = asyncio.create_task(channel.run())
    try:
        await asyncio.sleep(float(duration))
        if task.done():
            await task
            raise RuntimeError("market channel stopped unexpectedly")
    finally:
        await channel.close()
    await asyncio.wait_for(task, timeout=5)
    return {
        "connected": True,
        "tick_event_count": supervisor.tick_events,
    }


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _print_json(
    payload: Mapping[str, Any],
    *,
    stream: Any,
) -> None:
    print(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=stream,
    )


if __name__ == "__main__":
    raise SystemExit(main())
