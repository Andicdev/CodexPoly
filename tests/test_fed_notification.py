from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.fed import (
    FedOfficialObservation,
    FedRateDecision,
    fed_july_2026_decision_spec,
    fed_july_2026_market_bindings,
)
from cbr_trading.notifications import (
    source_event_notification_from_fed,
)
from cbr_trading.sources import (
    resolution_signal_from_fed_observation,
)


class FedNotificationTests(unittest.TestCase):
    def test_message_contains_source_and_all_market_outcomes(self) -> None:
        spec = fed_july_2026_decision_spec()
        signal = resolution_signal_from_fed_observation(
            FedOfficialObservation(
                provider="new_york_fed_statement_pdf",
                source_url=spec.new_york_fed_pdf_url,
                decision=FedRateDecision(
                    lower=Decimal("3.75"),
                    upper=Decimal("4.00"),
                ),
                detected_at=datetime(
                    2026,
                    7,
                    29,
                    18,
                    tzinfo=timezone.utc,
                ),
                document_fingerprint="c" * 64,
                excerpt="target range",
            ),
            spec=spec,
        )

        notification = source_event_notification_from_fed(
            signal=signal,
            bindings=fed_july_2026_market_bindings(),
        )

        self.assertEqual(
            notification.source_url,
            spec.new_york_fed_pdf_url,
        )
        self.assertIn(
            f"Source document: {spec.new_york_fed_pdf_url}",
            notification.message_text,
        )
        self.assertIn("increase_25: 25 == 25 -> YES", notification.message_text)
        self.assertIn("Market rules evaluated: 5", notification.message_text)


if __name__ == "__main__":
    unittest.main()
