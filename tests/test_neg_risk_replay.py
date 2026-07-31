from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from neg_risk_trading.replay import (
    DeterministicReplay,
    ReplayContractError,
    event_contract_from_payload,
    event_contract_payload,
)
from neg_risk_trading.repository import ReplayMessage, ReplaySession
from tests.test_neg_risk_recorder import _initial_dump
from tests.test_neg_risk_stream import NOW_MS, _configs, _event


SESSION_ID = UUID("22222222-3333-4444-5555-666666666666")
NOW = datetime.fromtimestamp(NOW_MS / 1000, tz=timezone.utc)


def _session(*, contract: bool = True) -> ReplaySession:
    event = _event()
    metadata: dict[str, object] = {
        "quantities": ["200"],
        "route_sample_interval_ms": 0,
    }
    if contract:
        metadata["event_contract"] = event_contract_payload(
            event=event,
            assets=_configs(event),
        )
    return ReplaySession(
        session_id=SESSION_ID,
        event_id=event.event_id,
        event_slug=event.slug,
        started_at=NOW,
        ended_at=NOW + timedelta(minutes=1),
        metadata=metadata,
    )


class EventContractTests(unittest.TestCase):
    def test_event_contract_round_trip_is_exact(self) -> None:
        event = _event()
        configs = _configs(event)

        restored_event, restored_configs = (
            event_contract_from_payload(
                event_contract_payload(
                    event=event,
                    assets=configs,
                )
            )
        )

        self.assertEqual(restored_event, event)
        self.assertEqual(restored_configs, configs)

    def test_legacy_session_without_contract_fails_closed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ReplayContractError,
            "^replay_event_contract_invalid$",
        ):
            DeterministicReplay(session=_session(contract=False))

    def test_missing_augmented_flag_fails_closed(self) -> None:
        event = _event()
        payload = event_contract_payload(
            event=event,
            assets=_configs(event),
        )
        del payload["event"]["augmented"]

        with self.assertRaisesRegex(
            ReplayContractError,
            "^replay_event_augmented_invalid$",
        ):
            event_contract_from_payload(payload)


class DeterministicReplayTests(unittest.TestCase):
    def test_replays_both_route_directions_deterministically(
        self,
    ) -> None:
        event = _event()
        message = ReplayMessage(
            connection_epoch=1,
            message_sequence=1,
            received_at=NOW,
            payload=_initial_dump(event),
        )
        replay = DeterministicReplay(session=_session())

        first = replay.run([message])
        second = replay.run([message])

        self.assertEqual(first, second)
        self.assertEqual(first["source_messages"], 1)
        self.assertEqual(first["evaluated_messages"], 1)
        self.assertEqual(len(first["routes"]), 10)
        self.assertEqual(
            {
                route["route_direction"]
                for route in first["routes"]
            },
            {"MAKER_BUY", "MAKER_SELL"},
        )
        self.assertTrue(
            all(
                route["quantity"] == "200"
                for route in first["routes"]
            )
        )

    def test_sequence_gap_fails_closed(self) -> None:
        event = _event()
        message = ReplayMessage(
            connection_epoch=1,
            message_sequence=2,
            received_at=NOW,
            payload=_initial_dump(event),
        )

        with self.assertRaisesRegex(
            ReplayContractError,
            "^replay_message_sequence_gap$",
        ):
            DeterministicReplay(
                session=_session(),
                quantities=(Decimal("200"),),
            ).run([message])


if __name__ == "__main__":
    unittest.main()
