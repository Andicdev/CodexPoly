from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.earnings import SqlAlchemyEarningsStore
from cbr_trading.execution import (
    PolymarketPreparedExecutor,
    PreparationContext,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.orchestration import (
    SqlAlchemyResolutionProfileStore,
    order_templates_from_profile,
)
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)
from cbr_trading.sources.earnings import EARNINGS_SOURCE_NAME
from cbr_trading.strategies import NUMERIC_THRESHOLD_STRATEGY_ID


_CONFIRMATION = "NO_SUBMIT_LIVE_PREPARATION"


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    if args.confirm != _CONFIRMATION:
        _print(
            {
                "ok": False,
                "error": "explicit prepare-only confirmation is required",
                "order_submitted": False,
            },
            stream=sys.stderr,
        )
        return 2

    runtime_environ = os.environ if environ is None else environ
    database = resolve_database_selection(
        "primary",
        runtime_environ,
    )
    if not database.url:
        _print(
            {
                "ok": False,
                "error": database.error or "database is not configured",
                "order_submitted": False,
            },
            stream=sys.stderr,
        )
        return 3

    profile_store = SqlAlchemyResolutionProfileStore(
        database_url=database.url
    )
    earnings_store = SqlAlchemyEarningsStore(
        database_url=database.url
    )
    executor: PolymarketPreparedExecutor | None = None
    try:
        profile_store.ensure_ready()
        earnings_store.ensure_ready()
        profile = profile_store.load(args.profile_key)
        if profile.source_name != EARNINGS_SOURCE_NAME:
            raise ValueError(
                "diagnostic supports earnings profiles only"
            )
        matching_rules = tuple(
            rule
            for rule in earnings_store.load_active_rules()
            if rule.scope_id == profile.scope_id
        )
        if len(matching_rules) != 1:
            raise ValueError(
                "profile does not have exactly one active earnings rule"
            )
        rule = matching_rules[0]
        templates = order_templates_from_profile(
            profile,
            strategy_id=NUMERIC_THRESHOLD_STRATEGY_ID,
            metadata={
                "rule_key": rule.rule_key,
                "ticker": rule.ticker,
                "diagnostic": "prepare_only",
            },
        )
        executor = PolymarketPreparedExecutor(
            database_url=database.url,
            safety=LiveSafetySettings.from_env(runtime_environ),
        )
        preparation = executor.prepare(
            templates,
            context=PreparationContext(
                scope_id=profile.scope_id,
                source=profile.source_name,
                source_reference=profile.source_reference,
                attributes={
                    "profile_key": profile.profile_key,
                    "ticker": rule.ticker,
                    "diagnostic": "prepare_only",
                },
            ),
        )
        item_errors = tuple(
            safe_error
            for item in preparation.items
            if (safe_error := _safe(item.error)) is not None
        )
        payload = {
            "ok": preparation.ready,
            "mode": "live_profile_prepare_only",
            "profile_key": profile.profile_key,
            "ticker": rule.ticker,
            "database_target": database.target,
            "order_submitted": False,
            "claim_reserved": False,
            "preparation": {
                "ready": preparation.ready,
                "error": item_errors[0] if item_errors else None,
                "maximum_notional": str(executor.maximum_notional),
                "items": [
                    {
                        "template_id": item.template_id,
                        "status": item.status.value,
                        "error": _safe(item.error),
                    }
                    for item in preparation.items
                ],
            },
            "markets": [
                {
                    "outcome": detail.outcome,
                    "quantity": str(detail.quantity),
                    "desired_price": str(detail.desired_price),
                    "effective_price": str(detail.effective_price),
                    "tick_size": str(detail.tick_size),
                    "minimum_order_size": str(
                        detail.minimum_order_size
                    ),
                    "best_bid": _decimal(detail.best_bid),
                    "best_ask": _decimal(detail.best_ask),
                    "order_presigned": detail.order_presigned,
                    "collateral_sufficient": (
                        detail.collateral_sufficient
                    ),
                }
                for detail in executor.details
            ],
        }
        _print(payload)
        return 0 if preparation.ready else 5
    except Exception as exc:
        _print(
            {
                "ok": False,
                "mode": "live_profile_prepare_only",
                "profile_key": args.profile_key,
                "error": redact_exception(exc),
                "order_submitted": False,
                "claim_reserved": False,
            },
            stream=sys.stderr,
        )
        return 5
    finally:
        if executor is not None:
            try:
                executor.close()
            except Exception:
                pass
        earnings_store.close()
        profile_store.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Repeat live executor preparation for one persisted earnings "
            "profile without reserving claims or submitting orders."
        )
    )
    parser.add_argument("--profile-key", required=True)
    parser.add_argument("--confirm", required=True)
    return parser


def _safe(value: object) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return redact_sensitive_text(normalized, max_length=500)


def _decimal(value: object) -> str | None:
    return None if value is None else str(value)


def _print(
    payload: object,
    *,
    stream: object = sys.stdout,
) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=stream,
    )


if __name__ == "__main__":
    raise SystemExit(main())
