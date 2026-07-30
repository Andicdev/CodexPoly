from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cbr_trading.earnings.catalog import (
    EarningsDocumentFormat,
    EarningsIntegrationStatus,
    EarningsMarketSession,
    EarningsReleaseCatalogEntry,
    EarningsTimingBasis,
    EarningsTimingConfidence,
)


_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "cbr_trading"
    / "migrations"
    / "011_add_earnings_release_catalog.sql"
)


class EarningsReleaseCatalogTests(unittest.TestCase):
    def test_entry_normalizes_ticker_and_times_to_utc(self) -> None:
        entry = EarningsReleaseCatalogEntry(
            event_key="nxpi:2026-07-28",
            ticker="nxpi",
            release_date=date(2026, 7, 28),
            market_session=EarningsMarketSession.POST_MARKET,
            schedule_source_url="https://investors.nxp.com/events/",
            integration_status=(
                EarningsIntegrationStatus.PARSER_ONLY
            ),
            document_format=EarningsDocumentFormat.FULL_HTML,
            conference_call_at=datetime(
                2026,
                7,
                28,
                22,
                30,
                tzinfo=timezone(timedelta(hours=2)),
            ),
            verified_at=datetime(
                2026,
                7,
                27,
                12,
                tzinfo=timezone.utc,
            ),
            metric_options={
                "reported": ["gaap_eps", "non_gaap_eps"],
                "market_basis": "unverified",
            },
            source_options=(
                {
                    "provider": "company_ir",
                    "delivery": "rss",
                    "status": "verified",
                },
            ),
        )

        self.assertEqual(entry.ticker, "NXPI")
        self.assertEqual(
            entry.conference_call_at,
            datetime(2026, 7, 28, 20, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            entry.source_options[0]["provider"],
            "company_ir",
        )

    def test_entry_rejects_insecure_schedule_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use https"):
            EarningsReleaseCatalogEntry(
                event_key="NXPI:2026-07-28",
                ticker="NXPI",
                release_date=date(2026, 7, 28),
                market_session=EarningsMarketSession.POST_MARKET,
                schedule_source_url="http://example.com",
                integration_status=(
                    EarningsIntegrationStatus.PARSER_ONLY
                ),
                document_format=EarningsDocumentFormat.FULL_HTML,
                verified_at=datetime.now(timezone.utc),
            )

    def test_entry_requires_complete_earliest_release_evidence(self) -> None:
        earliest = datetime(2026, 7, 30, 9, 30, tzinfo=timezone.utc)
        entry = EarningsReleaseCatalogEntry(
            event_key="VIRT:2026-07-30",
            ticker="VIRT",
            release_date=date(2026, 7, 30),
            market_session=EarningsMarketSession.PRE_MARKET,
            schedule_source_url="https://ir.virtu.com/events",
            integration_status=EarningsIntegrationStatus.PARSER_ONLY,
            document_format=EarningsDocumentFormat.FULL_HTML,
            verified_at=earliest,
            scheduled_release_at=earliest + timedelta(hours=1),
            conference_call_at=earliest + timedelta(hours=1, minutes=30),
            earliest_expected_release_at=earliest,
            timing_basis=EarningsTimingBasis.SESSION_FLOOR,
            timing_confidence=EarningsTimingConfidence.LOW,
            activation_safety_lead_seconds=1800,
            timing_source_url="https://ir.virtu.com/events",
        )

        self.assertEqual(entry.earliest_expected_release_at, earliest)
        self.assertEqual(entry.activation_safety_lead_seconds, 1800)

        with self.assertRaisesRegex(
            ValueError,
            "timing evidence requires",
        ):
            EarningsReleaseCatalogEntry(
                event_key="MA:2026-07-30",
                ticker="MA",
                release_date=date(2026, 7, 30),
                market_session=EarningsMarketSession.PRE_MARKET,
                schedule_source_url="https://investor.mastercard.com",
                integration_status=EarningsIntegrationStatus.PARSER_ONLY,
                document_format=EarningsDocumentFormat.MIXED,
                verified_at=earliest,
                timing_basis=EarningsTimingBasis.OFFICIAL_WINDOW,
            )

    def test_migration_is_additive_and_non_executable(self) -> None:
        text = _MIGRATION.read_text(encoding="utf-8").lower()

        self.assertIn(
            "create table if not exists earnings_release_catalog",
            text,
        )
        self.assertIn(
            "ux_earnings_release_catalog_ticker_date",
            text,
        )
        self.assertNotIn("drop table", text)
        self.assertNotIn("alter table", text)
        self.assertNotIn("resolution_execution_profiles", text)
        self.assertNotIn("earnings_market_rules", text)


if __name__ == "__main__":
    unittest.main()
