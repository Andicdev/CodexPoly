from __future__ import annotations

import argparse
import sys

from cbr_trading.secret_guard import redact_sensitive_text


def sanitized_matching_lines(
    payload: str,
    *,
    markers: tuple[str, ...],
) -> tuple[str, ...]:
    """Redact first, then retain only explicitly requested health lines."""

    if not markers:
        raise ValueError("at least one marker is required")
    safe_text = redact_sensitive_text(
        payload,
        max_length=1_000_000,
        preserve_newlines=True,
    )
    return tuple(
        line
        for line in safe_text.splitlines()
        if any(marker in line for marker in markers)
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Redact runtime log input and print only literal health markers."
        )
    )
    parser.add_argument(
        "--contains",
        action="append",
        dest="markers",
        required=True,
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=1_000_000,
    )
    args = parser.parse_args()
    if args.max_bytes < 1:
        parser.error("--max-bytes must be positive")
    payload = sys.stdin.buffer.read(args.max_bytes + 1)
    if len(payload) > args.max_bytes:
        print("runtime log input exceeded the safe limit", file=sys.stderr)
        return 2
    text = payload.decode("utf-8", errors="replace")
    for line in sanitized_matching_lines(
        text,
        markers=tuple(args.markers),
    ):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
