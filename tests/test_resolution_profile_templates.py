from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from cbr_trading.domain import RepriceOnTickChange
from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.orchestration import ResolutionProfileTemplate
from scripts.manage_resolution_profiles import (
    _build_parser,
    _profile_from_args,
    _template_from_args,
)


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "006_add_resolution_profile_templates.sql"
)


def _default_template() -> ResolutionProfileTemplate:
    return ResolutionProfileTemplate(
        template_key="default",
        yes_desired_price=Decimal("0.999"),
        no_desired_price=Decimal("0.999"),
        quantity=Decimal("50"),
        lifecycle_policy=RepriceOnTickChange(
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
            max_reprices=1,
        ),
        metadata={"purpose": "operator_default"},
    )


class ResolutionProfileTemplateTests(unittest.TestCase):
    def test_additive_migration_seeds_operator_default(self) -> None:
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
            "RESOLUTION_PROFILE_TEMPLATES",
            statements,
        )
        self.assertIn("'DEFAULT'", statements)
        self.assertIn("0.999", statements)
        self.assertIn("50", statements)
        self.assertIn(
            "ON CONFLICT (TEMPLATE_KEY) DO NOTHING",
            statements,
        )

    def test_earnings_profile_uses_stored_template_by_default(self) -> None:
        args = _build_parser().parse_args(
            [
                "--configure-earnings",
                "NVTS",
                "--account-name",
                "account",
                "--prepare-from",
                "2026-07-27T19:00:00Z",
                "--expires-at",
                "2026-07-28T03:00:00Z",
            ]
        )

        profile = _profile_from_args(
            nvts_q2_2026_shadow_rule(),
            args=args,
            template=_default_template(),
        )

        self.assertEqual(
            profile.yes_desired_price,
            Decimal("0.999"),
        )
        self.assertEqual(
            profile.no_desired_price,
            Decimal("0.999"),
        )
        self.assertEqual(profile.quantity, Decimal("50"))
        self.assertEqual(
            profile.metadata["profile_template_key"],
            "default",
        )
        self.assertIsInstance(
            profile.lifecycle_policy,
            RepriceOnTickChange,
        )

    def test_explicit_profile_value_overrides_only_that_value(self) -> None:
        args = _build_parser().parse_args(
            [
                "--configure-earnings",
                "NVTS",
                "--account-name",
                "account",
                "--yes-price",
                "0.95",
                "--prepare-from",
                "2026-07-27T19:00:00Z",
                "--expires-at",
                "2026-07-28T03:00:00Z",
            ]
        )

        profile = _profile_from_args(
            nvts_q2_2026_shadow_rule(),
            args=args,
            template=_default_template(),
        )

        self.assertEqual(
            profile.yes_desired_price,
            Decimal("0.95"),
        )
        self.assertEqual(
            profile.no_desired_price,
            Decimal("0.999"),
        )
        self.assertEqual(profile.quantity, Decimal("50"))

    def test_template_update_retains_omitted_values(self) -> None:
        args = _build_parser().parse_args(
            [
                "--set-template",
                "default",
                "--quantity",
                "75",
            ]
        )

        updated = _template_from_args(
            _default_template(),
            args=args,
        )

        self.assertEqual(updated.quantity, Decimal("75"))
        self.assertEqual(
            updated.yes_desired_price,
            Decimal("0.999"),
        )
        self.assertEqual(
            updated.lifecycle_policy.old_tick,
            Decimal("0.01"),
        )


if __name__ == "__main__":
    unittest.main()
