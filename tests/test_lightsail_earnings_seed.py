from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "001_initial_earnings_configuration.sql"
)
_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_initial_earnings_configuration.sql"
)
_WWD_SOURCE_MIGRATION = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "003_add_wwd_public_sources.sql"
)
_WWD_SOURCE_CHECK = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_wwd_public_sources.sql"
)


class LightsailEarningsSeedTests(unittest.TestCase):
    def test_seed_contains_exact_initial_rules_and_profiles(self) -> None:
        text = _SEED.read_text(encoding="utf-8")

        for rule_key in (
            "nvts-2026q2-nongaap-eps-neg0pt04",
            "wwd-2026q3-gaap-eps-2pt42",
            "bbby-2026q2-nongaap-eps-neg0pt26",
        ):
            self.assertIn(rule_key, text)
        for profile_key in (
            "earnings-nvts-2026q2",
            "earnings-wwd-2026q3",
            "earnings-bbby-2026q2",
        ):
            self.assertIn(profile_key, text)

        self.assertEqual(text.count("'abccbaq'"), 4)
        self.assertEqual(text.count("'DISABLED'"), 4)
        self.assertIn("trading_account_metadata", text)
        self.assertIn(
            "0x343FDd2bf9272Bd12cffBFE510f3969F57E36Df2",
            text,
        )
        self.assertIn('"ticker": "BBBY"', text)
        self.assertIn("0.999", text)
        self.assertIn("reprice_on_tick_change", text)

    def test_seed_does_not_copy_accounts_or_runtime_history(self) -> None:
        text = _SEED.read_text(encoding="utf-8").casefold()

        self.assertNotIn("insert into trading_accounts", text)
        self.assertNotIn("insert into earnings_source_events", text)
        self.assertNotIn("insert into earnings_fact_candidates", text)
        self.assertNotIn("insert into resolution_execution_claims", text)
        self.assertNotIn("delete from", text)
        self.assertNotIn("drop table", text)

    def test_wwd_public_source_migration_is_additive_and_checked(
        self,
    ) -> None:
        migration = _WWD_SOURCE_MIGRATION.read_text(encoding="utf-8")
        check = _WWD_SOURCE_CHECK.read_text(encoding="utf-8")

        self.assertIn("wordpress_rest", migration)
        self.assertIn("www.woodward.com/wp-json/wp/v2", migration)
        self.assertIn("globenewswire", migration)
        self.assertIn(
            "rule_key = 'wwd-2026q3-gaap-eps-2pt42'",
            migration,
        )
        self.assertNotIn("resolution_execution_profiles", migration)
        self.assertNotIn("DELETE FROM", migration)
        self.assertNotIn("DROP TABLE", migration)

        self.assertIn("BEGIN TRANSACTION READ ONLY", check)
        self.assertIn("wordpress_rest", check)
        self.assertIn("globenewswire", check)
        self.assertIn("ROLLBACK", check)
        self.assertNotIn("UPDATE ", check)

    def test_initial_check_is_read_only_and_covers_safety_invariants(
        self,
    ) -> None:
        text = _CHECK.read_text(encoding="utf-8")

        self.assertIn("BEGIN TRANSACTION READ ONLY", text)
        self.assertIn("ROLLBACK", text)
        self.assertIn("actual.account_name IS DISTINCT FROM 'abccbaq'", text)
        self.assertIn("actual.status IS DISTINCT FROM 'DISABLED'", text)
        self.assertIn("earnings_source_events", text)
        self.assertIn("earnings_fact_candidates", text)
        self.assertIn("resolution_execution_claims", text)
        self.assertIn("trading_account_metadata", text)
        self.assertIn("provider_event_id NOT LIKE 'staging-smoke-%'", text)
        self.assertIn("fact.status <> 'SUPERSEDED'", text)
        self.assertNotIn("INSERT INTO", text)
        self.assertNotIn("UPDATE ", text)
        self.assertNotIn("DELETE FROM", text)


if __name__ == "__main__":
    unittest.main()
