from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from cbr_trading.earnings.contracts import (
    EarningsSourceTiming,
    EarningsTransport,
)
from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.repository import (
    _MIGRATION_PATHS,
    _UPDATE_EVENT_STATUS_SQL,
    _UPSERT_DUPLICATE_TELEMETRY_SQL,
    _event_params,
    _timing_params,
)
from tests.test_earnings_navitas_parser import _DETECTED, _source


class EarningsSourceTelemetryTests(unittest.TestCase):
    def test_migration_is_additive_and_backfills_legacy_rows(self) -> None:
        migration = _MIGRATION_PATHS[-1]
        sql = migration.read_text(encoding="utf-8").casefold()

        self.assertEqual(
            migration.name,
            "016_add_earnings_source_telemetry.sql",
        )
        self.assertNotIn("drop table", sql)
        self.assertNotIn("drop column", sql)
        self.assertNotIn("alter table earnings_source_events", sql)
        self.assertIn(
            "create table if not exists "
            "earnings_source_processing_telemetry",
            sql,
        )
        self.assertIn(
            "earnings_source_transport_observations",
            sql,
        )
        self.assertIn("'legacy_unknown'", sql)

    def test_event_params_persist_exact_transport(self) -> None:
        candidate = replace(
            _source(nvts_q2_2026_shadow_rule()),
            transport=EarningsTransport.SEC_CURRENT_POLL,
        )

        params = _event_params(candidate, "event-key")

        self.assertEqual(
            params["source_transport"],
            "sec_current_poll",
        )
        self.assertEqual(
            params["transport_observed_at"],
            candidate.received_at,
        )
        self.assertIn(
            "observation_count + 1",
            _UPSERT_DUPLICATE_TELEMETRY_SQL,
        )

    def test_stage_timings_are_ordered_and_bound_to_update(self) -> None:
        timing = EarningsSourceTiming(
            transport=EarningsTransport.SEC_API_WEBSOCKET,
            transport_observed_at=_DETECTED,
            document_fetch_started_at=(
                _DETECTED + timedelta(milliseconds=1)
            ),
            document_fetch_completed_at=(
                _DETECTED + timedelta(milliseconds=4)
            ),
            document_fetch_route="sec_api_archive",
            parse_started_at=_DETECTED + timedelta(milliseconds=5),
            parse_completed_at=_DETECTED + timedelta(milliseconds=7),
            fact_persisted_at=_DETECTED + timedelta(milliseconds=9),
        )

        params = _timing_params(timing)

        self.assertEqual(
            params["document_fetch_route"],
            "sec_api_archive",
        )
        self.assertEqual(
            params["source_transport"],
            "sec_api_websocket",
        )
        self.assertEqual(
            params["fact_persisted_at"],
            timing.fact_persisted_at,
        )
        self.assertIn(
            "fact_persisted_at = coalesce(",
            _UPDATE_EVENT_STATUS_SQL,
        )

    def test_out_of_order_stage_timing_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "out of order"):
            EarningsSourceTiming(
                transport=EarningsTransport.COMPANY_IR_POLL,
                transport_observed_at=_DETECTED,
                document_fetch_started_at=(
                    _DETECTED + timedelta(milliseconds=2)
                ),
                document_fetch_completed_at=(
                    _DETECTED + timedelta(milliseconds=1)
                ),
            )


if __name__ == "__main__":
    unittest.main()
