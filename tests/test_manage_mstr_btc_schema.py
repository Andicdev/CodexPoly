from __future__ import annotations

import io
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from cbr_trading.db_config import DatabaseSelection
from cbr_trading.mstr_btc import (
    MstrBtcHoldingsBaseline,
    MstrBtcProvider,
    StoredMstrBtcHoldingsState,
)
from scripts import manage_mstr_btc_schema


class _Store:
    last: "_Store | None" = None

    def __init__(self, *, database_url: str):
        self.database_url = database_url
        self.migrated = False
        self.ready = False
        self.recorded = None
        self.pinned_before = None
        self.closed = False
        _Store.last = self

    def migrate(self) -> None:
        self.migrated = True

    def ensure_ready(self) -> None:
        self.ready = True

    def record_state(self, observation):
        self.recorded = observation
        return StoredMstrBtcHoldingsState(row_id=42, created=True)

    def pin_baseline(self, *, before):
        self.pinned_before = before
        return MstrBtcHoldingsBaseline(
            state_id="42",
            holdings_btc=843_775,
            as_of=datetime(2026, 7, 19, tzinfo=timezone.utc),
            provider=MstrBtcProvider.SEC,
            provider_event_id="0001193125-26-308369",
            source_url="https://www.sec.gov/mstr-20260720.htm",
        )

    def close(self) -> None:
        self.closed = True


class ManageMstrBtcSchemaTests(unittest.TestCase):
    def test_checked_in_baseline_has_exact_reviewed_public_data(self) -> None:
        observation = (
            manage_mstr_btc_schema.jul20_2026_baseline_observation()
        )

        self.assertEqual(observation.holdings_btc, 843_775)
        self.assertEqual(
            observation.provider_event_id,
            "0001193125-26-308369",
        )
        self.assertEqual(
            observation.observed_at,
            datetime(
                2026,
                7,
                20,
                12,
                0,
                16,
                tzinfo=timezone.utc,
            ),
        )
        self.assertEqual(observation.attributes["as_of_precision"], "date")

    def test_applies_records_and_pins_without_printing_source_details(
        self,
    ) -> None:
        output = io.StringIO()
        with (
            patch.object(
                manage_mstr_btc_schema,
                "resolve_database_selection",
                return_value=DatabaseSelection(
                    role="primary",
                    target="server_int",
                    source="DATABASE_APP_PASSWORD",
                    url="postgresql://unused",
                ),
            ),
            patch.object(
                manage_mstr_btc_schema,
                "SqlAlchemyMstrBtcHoldingsStore",
                _Store,
            ),
            patch.object(
                manage_mstr_btc_schema,
                "_load_dotenv_if_available",
            ),
            patch("sys.stdout", output),
        ):
            exit_code = manage_mstr_btc_schema.main(
                (
                    "--apply",
                    "--record-jul20-baseline",
                    "--pin-before",
                    "2026-07-21T04:00:00Z",
                )
            )

        self.assertEqual(exit_code, 0)
        assert _Store.last is not None
        self.assertTrue(_Store.last.migrated)
        self.assertTrue(_Store.last.ready)
        self.assertEqual(_Store.last.recorded.holdings_btc, 843_775)
        self.assertEqual(
            _Store.last.pinned_before,
            datetime(2026, 7, 21, 4, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(_Store.last.closed)
        payload = output.getvalue()
        self.assertIn('"holdings_btc": 843775', payload)
        self.assertNotIn("abc2e249", payload)
        self.assertNotIn("www.sec.gov", payload)

    def test_missing_database_fails_before_store_creation(self) -> None:
        error = io.StringIO()
        with (
            patch.object(
                manage_mstr_btc_schema,
                "resolve_database_selection",
                return_value=DatabaseSelection(
                    role="primary",
                    target="server_int",
                    source="DATABASE_APP_PASSWORD",
                    error="not configured",
                ),
            ),
            patch.object(
                manage_mstr_btc_schema,
                "_load_dotenv_if_available",
            ),
            patch("sys.stderr", error),
        ):
            exit_code = manage_mstr_btc_schema.main(())

        self.assertEqual(exit_code, 3)
        self.assertIn('"ok": false', error.getvalue())


if __name__ == "__main__":
    unittest.main()
