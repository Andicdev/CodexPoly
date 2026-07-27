from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Mapping


DEFAULT_SECRET_DIRECTORY = Path("/run/secrets")
_SAFE_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ACCOUNT_SECRET_SUFFIX = re.compile(r"[^A-Z0-9]+")
_MAX_SECRET_BYTES = 64 * 1024
TRADING_ACCOUNT_PRIVATE_KEY_PREFIX = (
    "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_"
)


class RuntimeSecretError(RuntimeError):
    """A value-safe error that identifies only the affected key."""


def trading_account_private_key_secret_name(
    account_name: str,
) -> str:
    """Return the canonical per-account encrypted-key variable name."""

    suffix = _ACCOUNT_SECRET_SUFFIX.sub(
        "_",
        str(account_name or "").strip().upper(),
    ).strip("_")
    if not suffix:
        raise ValueError("trading account name has no env-safe characters")
    return f"{TRADING_ACCOUNT_PRIVATE_KEY_PREFIX}{suffix}"


def read_runtime_secret(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    secret_directory: Path | str | None = None,
) -> str | None:
    """Resolve a runtime value from a file first, then the environment.

    An explicit ``<NAME>_FILE`` path is fail-closed. Without that override,
    Docker's conventional ``/run/secrets/<NAME>`` path is used when present.
    The ordinary environment value remains a local-development fallback.
    """

    key = _validated_name(name)
    env = environ if environ is not None else os.environ
    explicit_path = str(env.get(f"{key}_FILE") or "").strip()
    if explicit_path:
        return _read_secret_file(Path(explicit_path), key)

    directory = (
        Path(secret_directory)
        if secret_directory is not None
        else Path(
            str(
                env.get("CODEXPOLY_SECRET_DIR")
                or DEFAULT_SECRET_DIRECTORY
            )
        )
    )
    conventional_path = directory / key
    if conventional_path.exists() or conventional_path.is_symlink():
        return _read_secret_file(conventional_path, key)

    value = env.get(key)
    return None if value is None else str(value)


def runtime_secret_present(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    secret_directory: Path | str | None = None,
) -> bool:
    """Check presence without reading, hashing, or returning the value."""

    key = _validated_name(name)
    env = environ if environ is not None else os.environ
    explicit_path = str(env.get(f"{key}_FILE") or "").strip()
    if explicit_path:
        return _secret_file_is_present(Path(explicit_path))

    directory = (
        Path(secret_directory)
        if secret_directory is not None
        else Path(
            str(
                env.get("CODEXPOLY_SECRET_DIR")
                or DEFAULT_SECRET_DIRECTORY
            )
        )
    )
    conventional_path = directory / key
    if conventional_path.exists() or conventional_path.is_symlink():
        return _secret_file_is_present(conventional_path)
    return bool(str(env.get(key) or "").strip())


def _validated_name(name: str) -> str:
    key = str(name or "")
    if not _SAFE_NAME.fullmatch(key):
        raise ValueError("runtime secret name must be uppercase snake case")
    return key


def _secret_file_is_present(path: Path) -> bool:
    try:
        if path.is_symlink() or not path.is_file():
            return False
        return path.stat().st_size > 0
    except OSError:
        return False


def _read_secret_file(path: Path, key: str) -> str:
    try:
        if path.is_symlink():
            raise RuntimeSecretError(
                f"{key} secret file is not a regular file"
            )
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeSecretError(
                f"{key} secret file is not a regular file"
            )
        if info.st_size <= 0:
            raise RuntimeSecretError(f"{key} secret file is empty")
        if info.st_size > _MAX_SECRET_BYTES:
            raise RuntimeSecretError(f"{key} secret file is too large")
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except RuntimeSecretError:
        raise
    except (OSError, UnicodeError):
        raise RuntimeSecretError(
            f"{key} secret file is unavailable"
        ) from None
    if not value:
        raise RuntimeSecretError(f"{key} secret file is empty")
    return value
