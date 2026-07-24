from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

from cbr_trading.earnings.hosted_worker import _watches_from_rules
from cbr_trading.earnings.parsers.navitas import NavitasEpsParser
from cbr_trading.earnings.repository import SqlAlchemyEarningsStore
from cbr_trading.earnings.settings import EarningsWorkerSettings
from cbr_trading.secret_guard import redact_exception


def main(
    *,
    environ: Mapping[str, str] | None = None,
    store_factory: Callable[..., Any] = SqlAlchemyEarningsStore,
) -> int:
    _load_dotenv_if_available()
    env = environ if environ is not None else os.environ
    sec_credential_present = any(
        bool(str(env.get(name) or "").strip())
        for name in (
            "SEC_API_KEY",
            "SEC_API_IO_KEY",
            "SEC_API_STREAM_KEY",
        )
    )
    settings_env = dict(env)
    if not sec_credential_present:
        settings_env["SEC_API_KEY"] = "__preflight_missing__"
    try:
        settings = EarningsWorkerSettings.from_env(settings_env)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": redact_exception(exc),
                }
            ),
            file=sys.stderr,
        )
        return 3

    store = store_factory(database_url=settings.database_url)
    stage = "schema"
    try:
        store.ensure_ready()
        stage = "load_rules"
        rules = tuple(store.load_active_rules())
        stage = "build_watches"
        watches = _watches_from_rules(rules)
        stage = "check_parsers"
        configured_parsers = {"NVTS": NavitasEpsParser()}
        missing_parsers = sorted(
            {
                rule.ticker
                for rule in rules
                if rule.ticker not in configured_parsers
            }
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "database_target": settings.database_target,
                    "error": redact_exception(
                        RuntimeError(
                            "Earnings shadow preflight failed: "
                            f"stage={stage} type={type(exc).__name__}"
                        )
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 5
    finally:
        store.close()

    payload = {
        "ok": (
            sec_credential_present
            and bool(watches)
            and not missing_parsers
        ),
        "mode": settings.mode,
        "database_target": settings.database_target,
        "sec_credential_present": sec_credential_present,
        "active_rule_count": len(rules),
        "watch_count": len(watches),
        "scopes": [watch.scope_id for watch in watches],
        "missing_parsers": missing_parsers,
    }
    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=sys.stdout if payload["ok"] else sys.stderr,
    )
    return 0 if payload["ok"] else 5


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


if __name__ == "__main__":
    raise SystemExit(main())
