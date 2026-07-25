from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path
from typing import Iterable


_SAFE_SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SECRET_DIR_BY_ENV = {
    "staging": "staging",
    "production": "prod",
}


def _load_required_names(
    manifest_path: Path,
    *,
    environment: str,
    service: str | None,
) -> tuple[str, ...]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    environments = manifest.get("environments", {})
    services = environments.get(environment)
    if not isinstance(services, dict):
        raise ValueError(f"unknown environment: {environment}")

    if service is not None:
        names = services.get(service)
        if not isinstance(names, list):
            raise ValueError(
                f"unknown service for {environment}: {service}"
            )
        candidates: Iterable[object] = names
    else:
        candidates = (
            name
            for service_names in services.values()
            for name in service_names
        )

    required: list[str] = []
    for candidate in candidates:
        name = str(candidate)
        if not _SAFE_SECRET_NAME.fullmatch(name):
            raise ValueError(f"unsafe secret name in manifest: {name!r}")
        if name not in required:
            required.append(name)
    return tuple(required)


def _classify_secret_file(
    path: Path,
    *,
    expected_owner_uid: int | None,
) -> str:
    if path.is_symlink() or not path.is_file():
        return "missing"

    info = path.stat()
    if info.st_size <= 0:
        return "missing"

    if os.name == "posix":
        allowed_modes = {0o400, 0o444}
        if stat.S_IMODE(info.st_mode) not in allowed_modes:
            return "invalid_permissions"
        if (
            expected_owner_uid is not None
            and info.st_uid != expected_owner_uid
        ):
            return "invalid_owner"

    return "present"


def build_report(
    manifest_path: Path,
    secret_root: Path,
    *,
    environment: str,
    service: str | None = None,
    expected_owner_uid: int | None = 0,
) -> dict[str, object]:
    required = _load_required_names(
        manifest_path,
        environment=environment,
        service=service,
    )
    buckets: dict[str, list[str]] = {
        "present": [],
        "missing": [],
        "invalid_permissions": [],
        "invalid_owner": [],
    }

    for name in required:
        secret_dir = _SECRET_DIR_BY_ENV[environment]
        status = _classify_secret_file(
            secret_root / secret_dir / name,
            expected_owner_uid=expected_owner_uid,
        )
        buckets[status].append(name)

    return {
        "ok": not (
            buckets["missing"]
            or buckets["invalid_permissions"]
            or buckets["invalid_owner"]
        ),
        "environment": environment,
        "service": service,
        "required_count": len(required),
        "present_keys": buckets["present"],
        "missing_keys": buckets["missing"],
        "invalid_permission_keys": buckets["invalid_permissions"],
        "invalid_owner_keys": buckets["invalid_owner"],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check root-owned file secrets without reading or printing values."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("/opt/codexpoly/config/secret-manifest.json"),
    )
    parser.add_argument(
        "--secret-root",
        type=Path,
        default=Path("/opt/codexpoly/secrets"),
    )
    parser.add_argument(
        "--environment",
        choices=("staging", "production"),
        required=True,
    )
    parser.add_argument("--service")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        report = build_report(
            args.manifest,
            args.secret_root,
            environment=args.environment,
            service=args.service,
            expected_owner_uid=(
                os.geteuid()
                if args.environment == "staging"
                and hasattr(os, "geteuid")
                else 0
            ),
        )
    except Exception as exc:
        # Do not include exception text: it may contain an unexpected value.
        report = {
            "ok": False,
            "error": type(exc).__name__,
        }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
