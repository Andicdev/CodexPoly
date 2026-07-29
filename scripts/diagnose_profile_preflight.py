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
from cbr_trading.profile_lifecycle.settings import ProfileReadinessSettings
from cbr_trading.secret_guard import redact_sensitive_text


_ALLOWED_PROFILES = frozenset(
    {
        "earnings-iart-2026q2",
        "earnings-grmn-2026q2",
        "earnings-cbre-2026q2",
        "earnings-pag-2026q2",
    }
)


def main() -> int:
    requested = tuple(dict.fromkeys(sys.argv[1:]))
    if not requested or any(key not in _ALLOWED_PROFILES for key in requested):
        print("DIAG invalid_profile_selection")
        return 2

    settings = ProfileReadinessSettings.from_env(os.environ)
    safety = LiveSafetySettings.from_env(os.environ)
    store = SqlAlchemyResolutionProfileStore(
        database_url=settings.database_url
    )
    exit_code = 0
    try:
        for profile_key in requested:
            profile = store.load(profile_key)
            executor = PolymarketPreflightPreparedExecutor(
                database_url=settings.database_url or "",
                safety=safety,
            )
            try:
                summary = executor.prepare(
                    order_templates_from_profile(
                        profile,
                        strategy_id="profile_readiness_diagnostic",
                    ),
                    context=PreparationContext(
                        scope_id=profile.scope_id,
                        source=profile.source_name,
                        source_reference=profile.source_reference,
                        attributes={"profile_key": profile.profile_key},
                    ),
                )
                errors = sorted(
                    {
                        redact_sensitive_text(item.error)
                        for item in summary.items
                        if item.error
                    }
                )
                print(
                    "DIAG "
                    + json.dumps(
                        {
                            "profile": profile_key,
                            "ready": summary.ready,
                            "errors": errors,
                        },
                        sort_keys=True,
                    )
                )
                if not summary.ready:
                    exit_code = 1
            finally:
                executor.close()
    finally:
        store.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
