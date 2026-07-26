from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Sequence

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.mstr_btc import (
    MstrBtcHoldingsObservation,
    MstrBtcHoldingsValidationStatus,
    MstrBtcProvider,
    SqlAlchemyMstrBtcHoldingsStore,
)
from cbr_trading.secret_guard import redact_exception


_JUL20_SOURCE_URL = (
    "https://www.sec.gov/Archives/edgar/data/1050446/"
    "000119312526308369/mstr-20260720.htm"
)
_JUL20_DOCUMENT_FINGERPRINT = (
    "abc2e2494d982d961592ebf94d26f7ec"
    "1d83288f03e369e6daa1158f0d733e3f"
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check or explicitly manage the additive MSTR BTC holdings "
            "state schema."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Explicitly apply migration 008. Production should use the "
            "stdin-only migration runner instead."
        ),
    )
    parser.add_argument(
        "--record-jul20-baseline",
        action="store_true",
        help=(
            "Idempotently record only the checked-in July 20 SEC baseline."
        ),
    )
    parser.add_argument(
        "--pin-before",
        help=(
            "Return a safe summary of the validated baseline strictly "
            "before this timezone-aware ISO-8601 boundary."
        ),
    )
    args = parser.parse_args(argv)
    try:
        pin_before = (
            _parse_timestamp(args.pin_before, name="--pin-before")
            if args.pin_before
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))

    _load_dotenv_if_available()
    database = resolve_database_selection("primary", os.environ)
    if not database.url:
        print(
            json.dumps(
                {
                    "ok": False,
                    "target": database.target,
                    "error": (
                        database.error
                        or "Primary database URL is not configured"
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 3

    store = SqlAlchemyMstrBtcHoldingsStore(database_url=database.url)
    recorded: dict[str, object] | None = None
    pinned: dict[str, object] | None = None
    try:
        if args.apply:
            store.migrate()
        store.ensure_ready()
        if args.record_jul20_baseline:
            result = store.record_state(jul20_2026_baseline_observation())
            recorded = {
                "row_id": result.row_id,
                "created": result.created,
            }
        if pin_before is not None:
            baseline = store.pin_baseline(before=pin_before)
            pinned = {
                "state_id": baseline.state_id,
                "holdings_btc": baseline.holdings_btc,
                "as_of": baseline.as_of.isoformat(),
                "provider": baseline.provider.value,
                "provider_event_id": baseline.provider_event_id,
            }
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "target": database.target,
                    "applied": bool(args.apply),
                    "recorded_jul20_baseline": bool(
                        args.record_jul20_baseline
                    ),
                    "error": redact_exception(
                        RuntimeError(
                            "MSTR holdings schema operation failed: "
                            f"{type(exc).__name__}"
                        )
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 5
    finally:
        store.close()

    print(
        json.dumps(
            {
                "ok": True,
                "target": database.target,
                "applied": bool(args.apply),
                "schema_ready": True,
                "recorded": recorded,
                "pinned": pinned,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def jul20_2026_baseline_observation() -> MstrBtcHoldingsObservation:
    """Return the reviewed pre-window state from the July 20 MSTR 8-K."""

    return MstrBtcHoldingsObservation(
        holdings_btc=843_775,
        as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
        observed_at=datetime(
            2026,
            7,
            20,
            12,
            0,
            16,
            tzinfo=timezone.utc,
        ),
        provider=MstrBtcProvider.SEC,
        provider_event_id="0001193125-26-308369",
        source_url=_JUL20_SOURCE_URL,
        document_fingerprint=_JUL20_DOCUMENT_FINGERPRINT,
        validation_status=MstrBtcHoldingsValidationStatus.VALIDATED,
        attributes={
            "reported_as_of_date": "2026-07-19",
            "as_of_precision": "date",
            "filing_date": "2026-07-20",
            "ticker": "MSTR",
            "cik": "1050446",
        },
    )


def _parse_timestamp(value: str, *, name: str) -> datetime:
    normalized = str(value or "").strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError(
            f"{name} must be a valid ISO-8601 timestamp"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


if __name__ == "__main__":
    raise SystemExit(main())
