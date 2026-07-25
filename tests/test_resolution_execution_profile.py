from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from cbr_trading.domain import (
    KeepOpenPolicy,
    Outcome,
    RepriceOnTickChange,
)
from cbr_trading.orchestration import (
    ResolutionExecutionProfile,
    order_templates_from_profile,
)


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "005_add_resolution_execution_profiles.sql"
)


def _profile() -> ResolutionExecutionProfile:
    return ResolutionExecutionProfile(
        profile_key="earnings-nvts-2026q2",
        scope_id="earnings:NVTS:2026Q2",
        source_name="earnings_resolution",
        source_reference=(
            "https://polymarket.com/event/"
            "nvts-quarterly-earnings-nongaap-eps"
        ),
        account_name="test-account",
        condition_id="0xcondition",
        yes_desired_price=Decimal("0.999"),
        no_desired_price=Decimal("0.999"),
        quantity=Decimal("5"),
        prepare_from=datetime(
            2026, 7, 27, 19, tzinfo=timezone.utc
        ),
        expires_at=datetime(
            2026, 7, 28, 1, tzinfo=timezone.utc
        ),
        lifecycle_policy=RepriceOnTickChange(
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
        ),
        metadata={"rule_key": "nvts-2026q2"},
    )


class ResolutionExecutionProfileTests(unittest.TestCase):
    def test_builds_both_prepared_outcomes(self) -> None:
        yes, no = order_templates_from_profile(
            _profile(),
            strategy_id="numeric_threshold",
        )

        self.assertEqual(yes.outcome, Outcome.YES)
        self.assertEqual(no.outcome, Outcome.NO)
        self.assertEqual(yes.desired_price, Decimal("0.999"))
        self.assertEqual(no.quantity, Decimal("5"))
        self.assertEqual(
            yes.metadata["production_scope_id"],
            "earnings:NVTS:2026Q2",
        )
        self.assertNotEqual(yes.template_id, no.template_id)

    def test_accepts_keep_open_policy(self) -> None:
        profile = replace(
            _profile(),
            lifecycle_policy=KeepOpenPolicy(),
        )

        self.assertIsInstance(profile.lifecycle_policy, KeepOpenPolicy)

    def test_rejects_unsafe_price(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "yes_desired_price",
        ):
            replace(
                _profile(),
                yes_desired_price=Decimal("1"),
            )

    def test_migration_is_additive_and_disabled_by_default(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8")
        statements = "\n".join(
            line
            for line in sql.splitlines()
            if not line.lstrip().startswith("--")
        ).upper()

        self.assertNotIn("ALTER TABLE", statements)
        self.assertNotIn("DROP TABLE", statements)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS "
            "RESOLUTION_EXECUTION_PROFILES",
            statements,
        )
        self.assertIn("DEFAULT 'DISABLED'", statements)


if __name__ == "__main__":
    unittest.main()
