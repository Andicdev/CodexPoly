from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_SKIPPED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "reports",
    "tests",
}
_SKIPPED_SUFFIXES = {
    ".db",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".webp",
    ".zip",
}
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"""(?x)
    ^\s*(?:export\s+)?
    ["']?
    (?P<key>
        ACCOUNTS_MASTER_KEY|
        ANALYTICS_DATABASE_URL(?:_LOCAL|_SERVER_EXT|_SERVER_INT)?|
        CBR_ADMIN_DATABASE_URL|
        CBR_DATABASE_URL|
        CLOB_API_SECRET|
        DATABASE_URL(?:_LOCAL|_SERVER_EXT|_SERVER_INT)?|
        POLYMARKET_PRIVATE_KEY|
        PRIVATE_KEY|
        TG_BOT_TOKEN
    )
    ["']?\s*[:=]\s*
    (?P<value>.+?)\s*$
    """
)
_DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "telegram-token",
        re.compile(r"(?<![A-Za-z0-9_-])\d{6,12}:[A-Za-z0-9_-]{20,}"),
    ),
    (
        "uri-credentials",
        re.compile(
            r"(?i)\b[a-z][a-z0-9+.-]*://"
            r"[^/\s:@]+:[^@\s/]+@"
        ),
    ),
    (
        "pem-private-key",
        re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    ),
    (
        "hex-private-key",
        re.compile(
            r"(?i)(?<![0-9a-f])0x[0-9a-f]{64}(?![0-9a-f])"
        ),
    ),
)
_SAFE_VALUES = {
    "",
    "''",
    '""',
    "<secret>",
    "changeme",
    "example",
    "placeholder",
    "replace_me",
}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    detector: str


def _looks_like_placeholder(value: str) -> bool:
    cleaned = value.strip().rstrip(",").strip().strip("'\"").strip()
    lowered = cleaned.casefold()
    return (
        lowered in _SAFE_VALUES
        or cleaned.startswith("${")
        or cleaned.startswith("<")
        or cleaned.endswith("=") and not cleaned[:-1]
    )


def scan_text(text: str, *, path: Path) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        assignment = _SENSITIVE_ASSIGNMENT_RE.match(line)
        assignment_value = (
            assignment.group("value").strip()
            if assignment
            else ""
        )
        python_literal_assignment = (
            path.suffix.casefold() != ".py"
            or assignment_value.startswith(("'", '"'))
        )
        if (
            assignment
            and python_literal_assignment
            and not _looks_like_placeholder(assignment_value)
        ):
            findings.append(
                Finding(path, line_number, "sensitive-assignment")
            )
            continue
        for name, detector in _DETECTORS:
            match = detector.search(line)
            if not match:
                continue
            matched_text = match.group(0)
            if line.lstrip().startswith("#"):
                continue
            if name == "uri-credentials" and any(
                marker in matched_text
                for marker in (
                    "{",
                    "}",
                    "$",
                    "%",
                    "user:pass@",
                    "user:password@",
                    ".example",
                    "proxy.host",
                )
            ):
                continue
            if (
                name == "hex-private-key"
                and (
                    "PRIVATE_KEY" not in line.upper()
                    or len(set(matched_text[2:].casefold())) == 1
                )
            ):
                continue
            if match:
                findings.append(Finding(path, line_number, name))
                break
    return findings


def _candidate_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if (
            path.name == ".env"
            or (
                path.name.startswith(".env.")
                and path.name != ".env.example"
            )
        ):
            continue
        if any(part in _SKIPPED_DIRECTORIES for part in path.parts):
            continue
        if path.suffix.casefold() in _SKIPPED_SUFFIXES:
            continue
        yield path


def scan_repository(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _candidate_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(scan_text(text, path=path.relative_to(root)))
    return findings


def main() -> int:
    root = Path.cwd()
    findings = scan_repository(root)
    if findings:
        print("Secret scan failed. Values are intentionally not displayed.")
        for finding in findings:
            print(
                f"{finding.path}:{finding.line}: {finding.detector}"
            )
        return 1
    print("Secret scan passed: no high-confidence secrets detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
