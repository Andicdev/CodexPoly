from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from cbr_trading.domain import RepriceOnTickChange
from cbr_trading.execution import (
    PolymarketPreflightPreparedExecutor,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.mstr_btc import (
    SqlAlchemyMstrBtcAuditStore,
    mstr_jul21_27_market_bindings,
)
from cbr_trading.orchestration import (
    ResolutionExecutionProfile,
    SqlAlchemyResolutionProfileStore,
)
from cbr_trading.resolution_hosted import (
    HostedResolutionMode,
    HostedResolutionSettings,
    MstrBtcHostedResolutionWorker,
)
from cbr_trading.secret_guard import redact_exception
from cbr_trading.sources import MSTR_BTC_SOURCE_NAME


_CONFIRMATION = "PRODUCTION_MSTR_AUTHENTICATED_PREFLIGHT"
_ACCOUNT_NAME = "abccbaq"
_CHECKED_IN_EXPIRES_AT = datetime(
    2026,
    7,
    28,
    4,
    tzinfo=timezone.utc,
)
_PROFILE_KEY_BY_SIGNAL_ID = {
    "mstr-btc:2026-07-21:2026-07-27:purchase-any": (
        "mstr-jul21-27-purchase-any"
    ),
    "mstr-btc:2026-07-21:2026-07-27:purchase-over-1000": (
        "mstr-jul21-27-purchase-over-1000"
    ),
    "mstr-btc:2026-07-21:2026-07-27:sale-any": (
        "mstr-jul21-27-sale-any"
    ),
}


@dataclass(frozen=True)
class _ExpectedProfile:
    profile_key: str
    scope_id: str
    source_reference: str
    condition_id: str
    rule_key: str


def _expected_profiles() -> dict[str, _ExpectedProfile]:
    expected: dict[str, _ExpectedProfile] = {}
    for binding in mstr_jul21_27_market_bindings():
        profile_key = _PROFILE_KEY_BY_SIGNAL_ID[binding.signal_id]
        expected[profile_key] = _ExpectedProfile(
            profile_key=profile_key,
            scope_id=binding.signal_id,
            source_reference=binding.source_reference,
            condition_id=binding.condition_id,
            rule_key=binding.rule_key,
        )
    return expected


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings: HostedResolutionSettings | None = None
    audit_store: SqlAlchemyMstrBtcAuditStore | None = None
    profile_store: SqlAlchemyResolutionProfileStore | None = None
    worker: MstrBtcHostedResolutionWorker | None = None
    payload: dict[str, Any] | None = None
    failure: str | None = None
    try:
        settings = HostedResolutionSettings.from_env(os.environ)
        safety = LiveSafetySettings.from_env(os.environ)
        profile_store = SqlAlchemyResolutionProfileStore(
            database_url=settings.database_url,
        )
        profile_store.ensure_ready()
        profiles = tuple(
            profile_store.load_enabled(
                source_name=MSTR_BTC_SOURCE_NAME,
            )
        )
        guard_error = _production_guard_error(
            args=args,
            settings=settings,
            safety=safety,
            profiles=profiles,
            environ=os.environ,
            now=datetime.now(timezone.utc),
        )
        if guard_error is not None:
            raise ValueError(guard_error)

        audit_store = SqlAlchemyMstrBtcAuditStore(
            database_url=settings.database_url,
        )
        executors: dict[
            str,
            PolymarketPreflightPreparedExecutor,
        ] = {}

        def executor_factory(
            profile: ResolutionExecutionProfile,
        ) -> PolymarketPreflightPreparedExecutor:
            executor = PolymarketPreflightPreparedExecutor(
                database_url=settings.database_url or "",
                safety=safety,
            )
            executors[profile.profile_key] = executor
            return executor

        worker = MstrBtcHostedResolutionWorker(
            settings=settings,
            audit_store=audit_store,
            profile_store=profile_store,
            executor_factory=executor_factory,
        )
        preparations = worker.prepare()
        executor = executors.get(args.profile_key)
        if executor is None:
            raise RuntimeError(
                "authenticated executor was not created"
            )
        payload = _success_payload(
            profile=profiles[0],
            preparations=preparations,
            executor=executor,
            safety=safety,
            database_target=settings.database_target,
        )
    except Exception as exc:
        failure = redact_exception(exc)
    finally:
        if worker is not None:
            try:
                worker.close()
            except Exception:
                if failure is None:
                    failure = "RuntimeError"
        if audit_store is not None:
            audit_store.close()
        if profile_store is not None:
            profile_store.close()

    if failure is not None or payload is None:
        _print_json(
            {
                "ok": False,
                "mode": "production_mstr_btc_authenticated_preflight",
                "profile_key": args.profile_key,
                "order_submitted": False,
                "source_fact_polled": False,
                "error": failure or "preflight produced no result",
            },
            stream=sys.stderr,
        )
        return 5

    _print_json(
        payload,
        stream=sys.stdout if payload["ok"] else sys.stderr,
    )
    return 0 if payload["ok"] else 5


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Authenticate, load both outcome books, and pre-sign the two "
            "alternatives for exactly one checked-in MSTR profile. The "
            "command never polls a source fact and never submits an order."
        )
    )
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"Required literal confirmation: {_CONFIRMATION}.",
    )
    parser.add_argument(
        "--profile-key",
        required=True,
        choices=sorted(_expected_profiles()),
    )
    return parser


def _production_guard_error(
    *,
    args: argparse.Namespace,
    settings: HostedResolutionSettings,
    safety: LiveSafetySettings,
    profiles: Sequence[ResolutionExecutionProfile],
    environ: Mapping[str, str],
    now: datetime,
) -> str | None:
    if args.confirm != _CONFIRMATION:
        return "explicit production MSTR preflight confirmation is required"
    if str(environ.get("CODEXPOLY_ENVIRONMENT") or "").strip().lower() != (
        "production"
    ):
        return "CODEXPOLY_ENVIRONMENT must be production"
    if settings.mode is not HostedResolutionMode.PREFLIGHT:
        return "runner requires preflight mode"
    if settings.supervision_enabled:
        return "runner forbids order supervision"
    if safety.trading_enabled:
        return "runner forbids live trading"
    if safety.post_only:
        return "runner requires the reviewed non-post-only configuration"
    if safety.allowed_account.casefold() != _ACCOUNT_NAME:
        return "allowed account does not match the MSTR profile"
    if safety.max_order_quantity != Decimal("50"):
        return "maximum order quantity must equal 50"
    if safety.max_notional != Decimal("50"):
        return "maximum per-order notional must equal 50"
    if safety.max_total_notional != Decimal("100"):
        return "maximum prepared notional must equal 100"
    if not safety.accounts_master_key:
        return "account master key is not available"
    if (
        str(environ.get("TRADING_ACCOUNT_SOURCE") or "").strip().lower()
        != "database_metadata_secret"
    ):
        return "trading account source must use database metadata"
    if (
        str(environ.get("TRADING_ACCOUNT_NAME") or "").strip().casefold()
        != _ACCOUNT_NAME
    ):
        return "configured trading account does not match"
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
        return "runner requires the internal production database"
    if now.tzinfo is None or now.utcoffset() is None:
        return "preflight clock must be timezone-aware"
    expected = _expected_profiles().get(args.profile_key)
    if expected is None:
        return "profile key is not checked in"
    if len(profiles) != 1:
        return "exactly one MSTR profile must be enabled and in window"
    profile = profiles[0]
    if profile.profile_key != args.profile_key:
        return "enabled MSTR profile does not match the requested profile"
    if (
        profile.scope_id != expected.scope_id
        or profile.source_name != MSTR_BTC_SOURCE_NAME
        or profile.source_reference != expected.source_reference
        or profile.account_name.casefold() != _ACCOUNT_NAME
        or profile.condition_id.casefold()
        != expected.condition_id.casefold()
        or profile.yes_desired_price != Decimal("0.999")
        or profile.no_desired_price != Decimal("0.999")
        or profile.quantity != Decimal("50")
        or profile.expires_at != _CHECKED_IN_EXPIRES_AT
        or profile.metadata.get("rule_key") != expected.rule_key
    ):
        return "enabled MSTR profile does not match the checked-in baseline"
    policy = profile.lifecycle_policy
    if (
        not isinstance(policy, RepriceOnTickChange)
        or policy.old_tick != Decimal("0.01")
        or policy.new_tick != Decimal("0.001")
        or policy.max_reprices != 1
    ):
        return "enabled MSTR lifecycle policy does not match"
    current = now.astimezone(timezone.utc)
    if not profile.prepare_from <= current <= profile.expires_at:
        return "enabled MSTR profile is outside its preparation window"
    return None


def _success_payload(
    *,
    profile: ResolutionExecutionProfile,
    preparations: Sequence[Any],
    executor: PolymarketPreflightPreparedExecutor,
    safety: LiveSafetySettings,
    database_target: str,
) -> dict[str, Any]:
    details = tuple(executor.details)
    preparation_ready = (
        len(preparations) == 1
        and preparations[0].profile_key == profile.profile_key
        and preparations[0].ready
        and preparations[0].template_count == 2
    )
    market_ready = (
        len(details) == 2
        and {detail.outcome for detail in details} == {"YES", "NO"}
        and all(
            detail.quantity == Decimal("50")
            and detail.desired_price == Decimal("0.999")
            and detail.tick_size in {
                Decimal("0.01"),
                Decimal("0.001"),
            }
            and detail.effective_price
            == (
                Decimal("0.99")
                if detail.tick_size == Decimal("0.01")
                else Decimal("0.999")
            )
            and detail.minimum_order_size <= detail.quantity
            and detail.order_presigned
            and detail.collateral_sufficient
            for detail in details
        )
    )
    within_cap = (
        executor.maximum_notional > 0
        and safety.max_total_notional is not None
        and executor.maximum_notional <= safety.max_total_notional
    )
    return {
        "ok": bool(preparation_ready and market_ready and within_cap),
        "mode": "production_mstr_btc_authenticated_preflight",
        "profile_key": profile.profile_key,
        "database_target": database_target,
        "enabled_profile_count": 1,
        "order_submitted": False,
        "source_fact_polled": False,
        "executor_execute_called": False,
        "preparation": {
            "ready": preparation_ready,
            "template_count": (
                preparations[0].template_count
                if len(preparations) == 1
                else 0
            ),
            "maximum_notional": str(executor.maximum_notional),
        },
        "market": [
            {
                "outcome": detail.outcome,
                "quantity": str(detail.quantity),
                "desired_price": str(detail.desired_price),
                "effective_price": str(detail.effective_price),
                "tick_size": str(detail.tick_size),
                "minimum_order_size": str(
                    detail.minimum_order_size
                ),
                "best_bid": _decimal_or_none(detail.best_bid),
                "best_ask": _decimal_or_none(detail.best_ask),
                "order_presigned": detail.order_presigned,
                "collateral_sufficient": (
                    detail.collateral_sufficient
                ),
            }
            for detail in details
        ],
        "safety": {
            "live_trading_enabled": safety.trading_enabled,
            "supervision_enabled": False,
            "post_only": safety.post_only,
            "allowed_account_present": bool(
                safety.allowed_account
            ),
            "max_order_quantity": str(
                safety.max_order_quantity
            ),
            "max_notional": str(safety.max_notional),
            "max_total_notional": str(
                safety.max_total_notional
            ),
            "master_key_present": bool(
                safety.accounts_master_key
            ),
        },
    }


def _decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


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
