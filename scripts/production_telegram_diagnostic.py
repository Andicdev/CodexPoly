from __future__ import annotations

import json
import sys
from typing import Any

from cbr_trading.notifications.settings import NotificationWorkerSettings
from cbr_trading.secret_guard import redact_sensitive_text


def main() -> int:
    try:
        import requests

        settings = NotificationWorkerSettings.from_env()
        token = settings.telegram_bot_token or ""
        chat_id = settings.telegram_chat_id or ""
        base_url = f"https://api.telegram.org/bot{token}"

        get_me = requests.get(
            f"{base_url}/getMe",
            timeout=settings.telegram_timeout,
        )
        get_me_data = _object_or_empty(get_me)
        get_me_ok = get_me.status_code == 200 and bool(
            get_me_data.get("ok")
        )

        get_chat = requests.post(
            f"{base_url}/getChat",
            json={"chat_id": chat_id},
            timeout=settings.telegram_timeout,
        )
        get_chat_data = _object_or_empty(get_chat)
        get_chat_ok = get_chat.status_code == 200 and bool(
            get_chat_data.get("ok")
        )

        payload = {
            "ok": get_me_ok and get_chat_ok,
            "get_me": _result_summary(
                get_me.status_code,
                get_me_data,
            ),
            "get_chat": _result_summary(
                get_chat.status_code,
                get_chat_data,
            ),
        }
        print(
            json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0 if payload["ok"] else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": type(exc).__name__,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1


def _object_or_empty(response: Any) -> dict[str, Any]:
    try:
        value = response.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _result_summary(
    http_status: int,
    data: dict[str, Any],
) -> dict[str, object]:
    description = redact_sensitive_text(
        str(data.get("description") or ""),
        max_length=160,
    )
    return {
        "http_status": int(http_status),
        "ok": bool(data.get("ok")),
        "error_code": data.get("error_code"),
        "description": description or None,
    }


if __name__ == "__main__":
    raise SystemExit(main())
