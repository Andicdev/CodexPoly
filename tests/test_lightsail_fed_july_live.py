from pathlib import Path
import unittest


_ROOT = Path(__file__).resolve().parents[1]
_LIVE = _ROOT / "deploy" / "lightsail" / "live"
_CHECKS = _ROOT / "deploy" / "lightsail" / "checks"


class FedJulyLiveSqlTests(unittest.TestCase):
    def test_quantity_change_resets_readiness_without_enabling(self) -> None:
        text = (
            _LIVE / "027_prepare_fed_july_quantity_5000.sql"
        ).read_text(encoding="utf-8")

        self.assertEqual(text.count("quantity = 5000"), 2)
        self.assertIn("reviewed_notional <> 24975", text)
        self.assertIn("reviewed_notional > 26000", text)
        self.assertIn("state = 'PENDING'", text)
        self.assertNotIn("status = 'ENABLED'", text)

    def test_retry_is_limited_to_expected_cap_failures(self) -> None:
        text = (
            _LIVE / "028_retry_fed_july_preflight_after_caps.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("'preflight_valueerror'", text)
        self.assertIn("'authenticated_preflight_not_ready'", text)
        self.assertIn("profile.status = 'DISABLED'", text)
        self.assertNotIn("AUTO_LIVE", text)

    def test_arm_requires_readiness_and_live_heartbeat(self) -> None:
        text = (
            _LIVE / "029_arm_fed_july_quantity_5000.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("schedule.state = 'READY'", text)
        self.assertIn("schedule.readiness_valid_until", text)
        self.assertIn("runtime_key = 'hosted-resolution'", text)
        self.assertIn("automation_mode = 'AUTO_LIVE'", text)
        self.assertNotIn("profile.status = 'ENABLED'", text)

    def test_post_event_checks_are_read_only(self) -> None:
        names = (
            "verify_fed_july_executed_claims.sql",
            "verify_fed_july_lifecycle_complete.sql",
            "verify_fed_july_outcome_mapping.sql",
        )
        for name in names:
            with self.subTest(name=name):
                text = (_CHECKS / name).read_text(encoding="utf-8")
                self.assertIn("BEGIN TRANSACTION READ ONLY", text)
                self.assertIn("ROLLBACK;", text)


if __name__ == "__main__":
    unittest.main()
