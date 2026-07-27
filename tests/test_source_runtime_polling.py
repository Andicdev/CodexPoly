from __future__ import annotations

import unittest
from types import SimpleNamespace

from cbr_trading.source_runtime import ProfileWindowPollingGate


class _ProfileStore:
    def __init__(self, profiles):
        self.profiles = tuple(profiles)
        self.sources = []

    def load_enabled(self, *, source_name=None):
        self.sources.append(source_name)
        return self.profiles


class ProfileWindowPollingGateTests(unittest.TestCase):
    def test_inactive_without_enabled_in_window_profiles(self) -> None:
        store = _ProfileStore(())
        gate = ProfileWindowPollingGate(
            profile_store=store,
            source_name="mstr_btc_resolution",
        )

        self.assertFalse(gate.is_active())
        self.assertEqual(store.sources, ["mstr_btc_resolution"])

    def test_active_when_at_least_one_profile_is_loaded(self) -> None:
        gate = ProfileWindowPollingGate(
            profile_store=_ProfileStore((object(),)),
            source_name="earnings_resolution",
        )

        self.assertTrue(gate.is_active())

    def test_returns_unique_active_scope_ids(self) -> None:
        gate = ProfileWindowPollingGate(
            profile_store=_ProfileStore(
                (
                    SimpleNamespace(scope_id="earnings:NVTS:2026Q2"),
                    SimpleNamespace(scope_id="earnings:NVTS:2026Q2"),
                    SimpleNamespace(scope_id="earnings:WWD:2026Q3"),
                )
            ),
            source_name="earnings_resolution",
        )

        self.assertEqual(
            gate.active_scope_ids(),
            frozenset(
                {
                    "earnings:NVTS:2026Q2",
                    "earnings:WWD:2026Q3",
                }
            ),
        )

    def test_scope_query_rejects_malformed_profile(self) -> None:
        gate = ProfileWindowPollingGate(
            profile_store=_ProfileStore((object(),)),
            source_name="earnings_resolution",
        )

        with self.assertRaisesRegex(ValueError, "scope_id"):
            gate.active_scope_ids()


if __name__ == "__main__":
    unittest.main()
