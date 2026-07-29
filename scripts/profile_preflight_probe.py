from __future__ import annotations

import json
import os
import sys

from cbr_trading.execution import (
    PolymarketPreflightPreparedExecutor,
    PreparationContext,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.orchestration import (
    SqlAlchemyResolutionProfileStore,
    order_templates_from_profile,
)
from cbr_trading.profile_lifecycle.settings import (
    ProfileReadinessSettings,
)
from cbr_trading.secret_guard import redact_exception


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        _print(
            {
                "ok": False,
                "order_submitted": False,
                "error": "exactly one profile key is required",
            },
            stream=sys.stderr,
        )
        return 2

    profile_key = sys.argv[1].strip()
    store = None
    executor = None
    try:
        settings = ProfileReadinessSettings.from_env(os.environ)
        safety = LiveSafetySettings.from_env(os.environ)
        store = SqlAlchemyResolutionProfileStore(
            database_url=settings.database_url
        )
        profile = store.load(profile_key)
        templates = order_templates_from_profile(
            profile,
            strategy_id="manual_profile_readiness",
        )
        executor = PolymarketPreflightPreparedExecutor(
            database_url=settings.database_url or "",
            safety=safety,
        )
        summary = executor.prepare(
            templates,
            context=PreparationContext(
                scope_id=profile.scope_id,
                source=profile.source_name,
                source_reference=profile.source_reference,
                attributes={
                    "profile_key": profile.profile_key,
                    "manual_preflight": True,
                },
            ),
        )
        details = tuple(executor.details)
        ready = (
            summary.ready
            and len(summary.items) == len(templates)
            and len(details) == len(templates)
            and all(item.order_presigned for item in details)
        )
        _print(
            {
                "ok": ready,
                "mode": "profile_authenticated_preflight",
                "profile_key": profile.profile_key,
                "template_count": len(templates),
                "prepared_count": len(summary.items),
                "all_presigned": (
                    bool(details)
                    and all(item.order_presigned for item in details)
                ),
                "maximum_notional": str(executor.maximum_notional),
                "order_submitted": False,
                "executor_execute_called": False,
            },
            stream=sys.stdout if ready else sys.stderr,
        )
        return 0 if ready else 5
    except Exception as exc:
        _print(
            {
                "ok": False,
                "mode": "profile_authenticated_preflight",
                "profile_key": profile_key,
                "order_submitted": False,
                "executor_execute_called": False,
                "error": redact_exception(exc),
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
        if store is not None:
            store.close()


def _print(payload: dict[str, object], *, stream) -> None:
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=stream,
    )


if __name__ == "__main__":
    raise SystemExit(main())
