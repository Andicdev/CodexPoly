from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (
    ROOT
    / "deploy"
    / "lightsail"
    / "neg_risk"
    / "compose.staging.yml"
)


class NegRiskStagingDeploymentTests(unittest.TestCase):
    def test_runtime_image_contains_neg_risk_package(
        self,
    ) -> None:
        dockerfile = (
            ROOT / "Dockerfile"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "COPY neg_risk_trading neg_risk_trading",
            dockerfile,
        )

    def test_recorder_is_shadow_only_and_uses_isolated_database(
        self,
    ) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertIn(
            "DATABASE_NAME: codexpoly_neg_risk",
            compose,
        )
        self.assertIn(
            "NEG_RISK_RECORDER_MODE: shadow",
            compose,
        )
        self.assertIn(
            "neg_risk_trading.recorder_main",
            compose,
        )
        self.assertIn("read_only: true", compose)
        self.assertNotIn("ports:", compose)

    def test_catalog_scanner_is_shadow_only_and_bounded(
        self,
    ) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertIn(
            "neg_risk_trading.catalog_main",
            compose,
        )
        self.assertIn(
            "NEG_RISK_CATALOG_MODE: shadow",
            compose,
        )
        self.assertIn(
            'NEG_RISK_CATALOG_POLL_SEC: "900"',
            compose,
        )
        self.assertIn(
            'NEG_RISK_CATALOG_MAX_PAGES: "2000"',
            compose,
        )
        self.assertIn(
            'NEG_RISK_CATALOG_MAX_MARKETS: "200000"',
            compose,
        )

    def test_recorder_receives_no_trading_credentials(
        self,
    ) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")

        self.assertNotIn("ACCOUNTS_MASTER_KEY", compose)
        self.assertNotIn(
            "TRADING_ACCOUNT_PRIVATE_KEY",
            compose,
        )
        self.assertNotIn("CLOB_API_", compose)
        self.assertNotIn("CBR_LIVE_TRADING", compose)
        self.assertNotIn("TG_BOT_TOKEN", compose)


if __name__ == "__main__":
    unittest.main()
