from __future__ import annotations

import argparse
import getpass
import hmac
import os
import re
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path


MASTER_KEY_NAME = "ACCOUNTS_MASTER_KEY"
ENCRYPTED_KEY_NAME = "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED"
INSTALLED_SECRET_NAMES = (MASTER_KEY_NAME, ENCRYPTED_KEY_NAME)
_PRIVATE_KEY_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")


class AccountSecretInstallError(RuntimeError):
    """Value-safe account-secret installation failure."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def install_single_account_secrets(
    secret_directory: Path,
    *,
    secret_reader: Callable[[str], str] = getpass.getpass,
    require_root: bool = True,
) -> tuple[str, ...]:
    """Prompt for one private key and install a fresh Fernet key pair."""

    directory = Path(secret_directory)
    if (
        require_root
        and hasattr(os, "geteuid")
        and os.geteuid() != 0
    ):
        raise AccountSecretInstallError("root-required")

    _ensure_secret_directory(directory)
    destinations = tuple(
        directory / name for name in INSTALLED_SECRET_NAMES
    )
    if any(path.exists() or path.is_symlink() for path in destinations):
        raise AccountSecretInstallError("account-secret-already-exists")

    private_key = secret_reader("Enter Polymarket private key: ")
    confirmation = secret_reader("Confirm Polymarket private key: ")
    if not private_key or not confirmation:
        raise AccountSecretInstallError("empty-private-key")
    if not hmac.compare_digest(private_key, confirmation):
        raise AccountSecretInstallError("private-key-mismatch")
    if not _PRIVATE_KEY_RE.fullmatch(private_key):
        raise AccountSecretInstallError("invalid-private-key-format")

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise AccountSecretInstallError(
            "cryptography-unavailable"
        ) from None

    master_key = Fernet.generate_key()
    encrypted_key = Fernet(master_key).encrypt(
        private_key.encode("utf-8")
    )
    temporary_paths: list[Path] = []
    installed_paths: list[Path] = []
    try:
        for name, value in (
            (MASTER_KEY_NAME, master_key),
            (ENCRYPTED_KEY_NAME, encrypted_key),
        ):
            temporary_paths.append(
                _write_temporary_secret(
                    directory,
                    name=name,
                    value=value,
                )
            )
        for temporary_path, destination in zip(
            temporary_paths,
            destinations,
            strict=True,
        ):
            os.replace(temporary_path, destination)
            installed_paths.append(destination)
    except Exception:
        for temporary_path in temporary_paths:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        for installed_path in installed_paths:
            try:
                installed_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise AccountSecretInstallError("atomic-install-failed") from None
    finally:
        private_key = ""
        confirmation = ""
        master_key = b""
        encrypted_key = b""

    return INSTALLED_SECRET_NAMES


def _ensure_secret_directory(directory: Path) -> None:
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise AccountSecretInstallError(
                "invalid-secret-directory"
            )
        if os.name == "posix":
            info = directory.stat()
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise AccountSecretInstallError(
                    "invalid-secret-directory-permissions"
                )
            if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
                raise AccountSecretInstallError(
                    "invalid-secret-directory-owner"
                )
    except AccountSecretInstallError:
        raise
    except OSError:
        raise AccountSecretInstallError(
            "secret-directory-unavailable"
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
        path.chmod(0o444)
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
            "Install a fresh master key and encrypted private key "
            "without displaying either value."
        )
    )
    parser.add_argument(
        "--secret-directory",
        type=Path,
        default=Path("/run/install-secrets"),
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        installed = install_single_account_secrets(
            args.secret_directory
        )
    except AccountSecretInstallError as exc:
        print("ACCOUNT_SECRET_INSTALL_RESULT=failed")
        print(f"ACCOUNT_SECRET_INSTALL_REASON={exc.reason}")
        return 1
    except Exception as exc:
        print("ACCOUNT_SECRET_INSTALL_RESULT=failed")
        print(
            "ACCOUNT_SECRET_INSTALL_REASON="
            f"{type(exc).__name__}"
        )
        return 1

    print("ACCOUNT_SECRET_INSTALL_RESULT=installed")
    for name in installed:
        print(f"ACCOUNT_SECRET_INSTALLED={name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
