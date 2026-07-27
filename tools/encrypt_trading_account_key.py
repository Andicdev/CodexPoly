from __future__ import annotations

import argparse
import getpass
import hmac
import os
import re
import stat
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from cbr_trading.runtime_secrets import (
    trading_account_private_key_secret_name,
)


MASTER_KEY_NAME = "ACCOUNTS_MASTER_KEY"
_PRIVATE_KEY_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")
_MAX_MASTER_KEY_BYTES = 1024


class TradingAccountKeyEncryptionError(RuntimeError):
    """Value-safe failure that never includes supplied secret values."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def encrypt_trading_account_key(
    output_directory: Path,
    *,
    account_name: str,
    master_key_mode: str = "auto",
    secret_reader: Callable[[str], str] = getpass.getpass,
) -> tuple[Path, Path]:
    """Encrypt one account PK while sharing one local Fernet master key."""

    try:
        encrypted_key_name = (
            trading_account_private_key_secret_name(account_name)
        )
    except ValueError:
        raise TradingAccountKeyEncryptionError(
            "invalid-account-name"
        ) from None

    mode = str(master_key_mode or "").strip().casefold()
    if mode not in {"auto", "generate", "prompt"}:
        raise TradingAccountKeyEncryptionError(
            "unsupported-master-key-mode"
        )

    directory = Path(output_directory)
    _ensure_private_directory(directory)
    master_path = directory / MASTER_KEY_NAME
    encrypted_path = directory / encrypted_key_name
    if encrypted_path.exists() or encrypted_path.is_symlink():
        raise TradingAccountKeyEncryptionError(
            "account-secret-already-exists"
        )

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise TradingAccountKeyEncryptionError(
            "cryptography-unavailable"
        ) from None

    master_key, install_master_key = _resolve_master_key(
        master_path,
        mode=mode,
        secret_reader=secret_reader,
        fernet_type=Fernet,
    )
    private_key = _read_confirmed_secret(
        secret_reader,
        label=f"Polymarket private key for {account_name}",
    )
    if not _PRIVATE_KEY_RE.fullmatch(private_key):
        raise TradingAccountKeyEncryptionError(
            "invalid-private-key-format"
        )

    encrypted_key = Fernet(master_key).encrypt(
        private_key.encode("utf-8")
    )
    try:
        files_to_install = [(encrypted_path, encrypted_key)]
        if install_master_key:
            files_to_install.insert(0, (master_path, master_key))
        _install_secret_files(
            directory,
            files_to_install=files_to_install,
        )
        return master_path, encrypted_path
    finally:
        private_key = ""
        master_key = b""
        encrypted_key = b""


def _resolve_master_key(
    master_path: Path,
    *,
    mode: str,
    secret_reader: Callable[[str], str],
    fernet_type: Any,
) -> tuple[bytes, bool]:
    master_exists = master_path.exists() or master_path.is_symlink()

    if mode == "auto":
        if master_exists:
            return (
                _read_and_validate_master_key(
                    master_path,
                    fernet_type=fernet_type,
                ),
                False,
            )
        return fernet_type.generate_key(), True

    if mode == "generate":
        if master_exists:
            raise TradingAccountKeyEncryptionError(
                "master-key-already-exists"
            )
        return fernet_type.generate_key(), True

    supplied = _read_confirmed_secret(
        secret_reader,
        label=MASTER_KEY_NAME,
    )
    try:
        supplied_bytes = supplied.encode("ascii")
        _validate_master_key(
            supplied_bytes,
            fernet_type=fernet_type,
        )
        if not master_exists:
            return supplied_bytes, True

        existing = _read_and_validate_master_key(
            master_path,
            fernet_type=fernet_type,
        )
        if not hmac.compare_digest(existing, supplied_bytes):
            raise TradingAccountKeyEncryptionError(
                "supplied-master-key-does-not-match-existing"
            )
        return existing, False
    except UnicodeEncodeError:
        raise TradingAccountKeyEncryptionError(
            "invalid-master-key"
        ) from None
    finally:
        supplied = ""


def _read_and_validate_master_key(
    path: Path,
    *,
    fernet_type: Any,
) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise TradingAccountKeyEncryptionError(
                "invalid-master-key-file"
            )
        info = path.stat()
        if info.st_size <= 0 or info.st_size > _MAX_MASTER_KEY_BYTES:
            raise TradingAccountKeyEncryptionError(
                "invalid-master-key-file"
            )
        value = path.read_bytes().strip()
    except TradingAccountKeyEncryptionError:
        raise
    except OSError:
        raise TradingAccountKeyEncryptionError(
            "master-key-file-unavailable"
        ) from None

    _validate_master_key(value, fernet_type=fernet_type)
    return value


def _validate_master_key(
    value: bytes,
    *,
    fernet_type: Any,
) -> None:
    try:
        fernet_type(value)
    except (TypeError, ValueError):
        raise TradingAccountKeyEncryptionError(
            "invalid-master-key"
        ) from None


def _read_confirmed_secret(
    secret_reader: Callable[[str], str],
    *,
    label: str,
) -> str:
    value = str(secret_reader(f"Enter {label}: ") or "").strip()
    confirmation = str(
        secret_reader(f"Confirm {label}: ") or ""
    ).strip()
    if not value or not confirmation:
        raise TradingAccountKeyEncryptionError("empty-secret")
    if not hmac.compare_digest(value, confirmation):
        raise TradingAccountKeyEncryptionError(
            "secret-confirmation-mismatch"
        )
    return value


def _install_secret_files(
    directory: Path,
    *,
    files_to_install: Sequence[tuple[Path, bytes]],
) -> None:
    if any(
        path.exists() or path.is_symlink()
        for path, _value in files_to_install
    ):
        raise TradingAccountKeyEncryptionError(
            "secret-output-already-exists"
        )

    temporary_paths: list[Path] = []
    installed_paths: list[Path] = []
    try:
        for destination, value in files_to_install:
            temporary_paths.append(
                _write_temporary_secret(
                    directory,
                    name=destination.name,
                    value=value,
                )
            )
        for temporary_path, (destination, _value) in zip(
            temporary_paths,
            files_to_install,
            strict=True,
        ):
            os.replace(temporary_path, destination)
            installed_paths.append(destination)
    except TradingAccountKeyEncryptionError:
        raise
    except Exception:
        raise TradingAccountKeyEncryptionError(
            "atomic-secret-install-failed"
        ) from None
    finally:
        for temporary_path in temporary_paths:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        if len(installed_paths) != len(files_to_install):
            for installed_path in installed_paths:
                try:
                    installed_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _ensure_private_directory(directory: Path) -> None:
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise TradingAccountKeyEncryptionError(
                "invalid-output-directory"
            )
        if os.name == "posix":
            directory.chmod(0o700)
            if stat.S_IMODE(directory.stat().st_mode) != 0o700:
                raise TradingAccountKeyEncryptionError(
                    "unsafe-output-directory-permissions"
                )
    except TradingAccountKeyEncryptionError:
        raise
    except OSError:
        raise TradingAccountKeyEncryptionError(
            "output-directory-unavailable"
        ) from None


def _write_temporary_secret(
    directory: Path,
    *,
    name: str,
    value: bytes,
) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{name}.",
        dir=directory,
    )
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o600)
        return path
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Encrypt one account-specific Polymarket private key into "
            "local secret files without displaying secret values."
        )
    )
    parser.add_argument(
        "--account-name",
        required=True,
        help=(
            "TradingAccount.name used to derive the uppercase env suffix."
        ),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path(".local-secrets"),
    )
    parser.add_argument(
        "--master-key-mode",
        choices=("auto", "generate", "prompt"),
        default="auto",
        help=(
            "Auto reuses a local master file or generates it; generate "
            "requires no existing file; prompt accepts an existing key."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        master_path, encrypted_path = encrypt_trading_account_key(
            args.output_directory,
            account_name=args.account_name,
            master_key_mode=args.master_key_mode,
        )
    except TradingAccountKeyEncryptionError as exc:
        print("TRADING_ACCOUNT_KEY_ENCRYPTION_RESULT=failed")
        print(
            "TRADING_ACCOUNT_KEY_ENCRYPTION_REASON="
            f"{exc.reason}"
        )
        return 1
    except Exception as exc:
        print("TRADING_ACCOUNT_KEY_ENCRYPTION_RESULT=failed")
        print(
            "TRADING_ACCOUNT_KEY_ENCRYPTION_REASON="
            f"{type(exc).__name__}"
        )
        return 1

    print("TRADING_ACCOUNT_KEY_ENCRYPTION_RESULT=created")
    print(f"{MASTER_KEY_NAME}_FILE={master_path.resolve()}")
    print(f"{encrypted_path.name}_FILE={encrypted_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
