from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Mapping, Sequence


PROTECTED_RUNTIME_KEYS: tuple[str, ...] = (
    "DATABASE_URL_SERVER_EXT",
    "ACCOUNTS_MASTER_KEY",
    "TG_BOT_TOKEN",
    "TELEGRAM_INGEST_CHAT_ID",
)

SENSITIVE_ENV_KEYS: frozenset[str] = frozenset(
    {
        "ACCOUNTS_MASTER_KEY",
        "ANALYTICS_DATABASE_URL",
        "ANALYTICS_DATABASE_URL_LOCAL",
        "ANALYTICS_DATABASE_URL_SERVER_EXT",
        "ANALYTICS_DATABASE_URL_SERVER_INT",
        "CBR_ADMIN_DATABASE_URL",
        "CBR_DATABASE_URL",
        "CLOB_API_KEY",
        "CLOB_API_SECRET",
        "DATABASE_URL",
        "DATABASE_URL_LOCAL",
        "DATABASE_URL_SERVER_EXT",
        "DATABASE_URL_SERVER_INT",
        "POLYMARKET_PRIVATE_KEY",
        "PRIVATE_KEY",
        "TELEGRAM_INGEST_CHAT_ID",
        "TG_BOT_TOKEN",
    }
)

_KEY_NAMES = "|".join(
    re.escape(name)
    for name in sorted(SENSITIVE_ENV_KEYS, key=len, reverse=True)
)
_ASSIGNMENT_RE = re.compile(
    rf"(?i)(?<![A-Z0-9_])"
    rf"(?P<key>{_KEY_NAMES})"
    rf"(?P<separator>\s*[:=]\s*)"
    rf"(?P<value>[^\s,;}}\]]+)"
)
_URI_CREDENTIALS_RE = re.compile(
    r"(?i)\b(?P<scheme>[a-z][a-z0-9+.-]*://)"
    r"[^/\s:@]+:[^@\s/]+@"
)
_TELEGRAM_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])\d{6,12}:[A-Za-z0-9_-]{20,}"
)
_TELEGRAM_BOT_PATH_RE = re.compile(
    r"(?i)(?P<prefix>/bot)[^/\s?]+"
)
_HEX_PRIVATE_KEY_RE = re.compile(
    r"(?i)(?<![0-9a-f])0x[0-9a-f]{64}(?![0-9a-f])"
)
_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----.*?"
    r"-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----",
    re.DOTALL,
)


@dataclass(frozen=True)
class SecretPresenceReport:
    required_keys: tuple[str, ...]
    present_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing_keys

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "required_count": len(self.required_keys),
            "present_keys": list(self.present_keys),
            "missing_keys": list(self.missing_keys),
        }


def redact_sensitive_text(
    value: object,
    *,
    max_length: int = 240,
) -> str:
    """Return log-safe text without exposing common credential formats."""

    text = " ".join(str(value or "").split())
    text = _PEM_PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", text)
    text = _ASSIGNMENT_RE.sub(
        lambda match: (
            f"{match.group('key')}"
            f"{match.group('separator')}[REDACTED]"
        ),
        text,
    )
    text = _URI_CREDENTIALS_RE.sub(
        lambda match: f"{match.group('scheme')}[REDACTED]@",
        text,
    )
    text = _TELEGRAM_BOT_PATH_RE.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]",
        text,
    )
    text = _TELEGRAM_TOKEN_RE.sub("[REDACTED_TELEGRAM_TOKEN]", text)
    text = _HEX_PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", text)
    return text[:max_length]


def redact_exception(
    exc: BaseException,
    *,
    max_length: int = 240,
) -> str:
    detail = redact_sensitive_text(exc, max_length=max_length)
    return (
        f"{type(exc).__name__}: {detail}"
        if detail
        else type(exc).__name__
    )


def secret_presence(
    environ: Mapping[str, str],
    required_keys: Sequence[str] = PROTECTED_RUNTIME_KEYS,
) -> SecretPresenceReport:
    required = tuple(dict.fromkeys(str(key) for key in required_keys))
    present = tuple(
        key
        for key in required
        if bool(str(environ.get(key) or "").strip())
    )
    missing = tuple(key for key in required if key not in present)
    return SecretPresenceReport(
        required_keys=required,
        present_keys=present,
        missing_keys=missing,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check required runtime secret presence without printing values, "
            "lengths, hashes, or connection details."
        )
    )
    parser.add_argument(
        "--required",
        action="append",
        dest="required_keys",
        help=(
            "Required environment key. Repeat for multiple keys. "
            "Defaults to the CBR Northflank protected runtime keys."
        ),
    )
    args = parser.parse_args(argv)
    report = secret_presence(
        os.environ,
        args.required_keys or PROTECTED_RUNTIME_KEYS,
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
