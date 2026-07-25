from __future__ import annotations

import json
import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_DEPLOY = _ROOT / "deploy" / "lightsail"
_WORKERS = _DEPLOY / "workers"
_DOCKERFILE = _ROOT / "Dockerfile"


class LightsailWorkerDeploymentTests(unittest.TestCase):
    def test_image_contains_deployment_files_used_by_embedded_tests(
        self,
    ) -> None:
        text = _DOCKERFILE.read_text(encoding="utf-8")

        self.assertIn("COPY deploy deploy", text)
        self.assertLess(
            text.index("COPY deploy deploy"),
            text.index("RUN python -m unittest discover"),
        )

    def test_manifest_keeps_staging_without_trading_secrets(self) -> None:
        manifest = json.loads(
            (_DEPLOY / "secret-manifest.json").read_text(
                encoding="utf-8"
            )
        )

        staging = manifest["environments"]["staging"]
        production = manifest["environments"]["production"]

        self.assertEqual(
            staging["resolution-worker"],
            ["DATABASE_APP_PASSWORD"],
        )
        self.assertEqual(
            production["resolution-worker"],
            ["DATABASE_APP_PASSWORD"],
        )
        self.assertEqual(
            production["resolution-worker-trading"],
            [
                "DATABASE_APP_PASSWORD",
                "ACCOUNTS_MASTER_KEY",
                "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED",
            ],
        )

    def test_base_worker_files_are_private_and_shadow_only(self) -> None:
        for name, network in (
            ("compose.staging.yml", "codexpoly-staging-backend"),
            ("compose.production.yml", "codexpoly-production-backend"),
        ):
            text = (_WORKERS / name).read_text(encoding="utf-8")
            self.assertNotIn("\n    ports:", text)
            self.assertNotIn("POSTGRES_PASSWORD", text)
            self.assertNotIn("ACCOUNTS_MASTER_KEY", text)
            self.assertNotIn(
                "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED",
                text,
            )
            self.assertIn(
                "RESOLUTION_ORCHESTRATOR_MODE: shadow",
                text,
            )
            self.assertIn(f"name: {network}", text)
            self.assertIn("external: true", text)
            self.assertIn(
                'command: ["python", "-u", "-m", '
                '"cbr_trading.earnings"]',
                text,
            )
            self.assertIn(
                'command: ["python", "-u", "-m", '
                '"cbr_trading.resolution_hosted"]',
                text,
            )

    def test_production_overlay_is_the_only_trading_mount(self) -> None:
        text = (
            _WORKERS / "compose.production.trading.yml"
        ).read_text(encoding="utf-8")

        self.assertNotIn("\n    ports:", text)
        self.assertIn(
            "TRADING_ACCOUNT_SOURCE: single_secret",
            text,
        )
        self.assertIn("TRADING_ACCOUNT_NAME: abccbaq", text)
        self.assertIn(
            "TRADING_ACCOUNT_VENUE: polymarket_clob",
            text,
        )
        self.assertIn(
            'TRADING_ACCOUNT_SIGNATURE_TYPE: "2"',
            text,
        )
        self.assertIn(
            "/run/secrets/ACCOUNTS_MASTER_KEY",
            text,
        )
        self.assertIn(
            "/run/secrets/"
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED",
            text,
        )
        self.assertIn(
            "CBR_LIVE_TRADING_ENABLED:"
            ' "${CBR_LIVE_TRADING_ENABLED:-0}"',
            text,
        )
        self.assertIn(
            "RESOLUTION_SUPERVISION_ENABLED:"
            ' "${RESOLUTION_SUPERVISION_ENABLED:-0}"',
            text,
        )

    def test_individual_installer_refuses_account_secret_pair(self) -> None:
        text = (_DEPLOY / "install-secret.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'secret_name}" == "ACCOUNTS_MASTER_KEY"',
            text,
        )
        self.assertIn(
            'secret_name}" == '
            '"TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED"',
            text,
        )

    def test_account_installer_has_no_network_or_secret_arguments(self) -> None:
        text = (_DEPLOY / "install-trading-account.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("--network none", text)
        self.assertIn("--read-only", text)
        self.assertIn("--cap-drop ALL", text)
        self.assertIn("no-new-privileges:true", text)
        self.assertIn("@sha256:", text)
        self.assertNotIn("--env ACCOUNTS_MASTER_KEY", text)
        self.assertNotIn("--env PRIVATE_KEY", text)


if __name__ == "__main__":
    unittest.main()
