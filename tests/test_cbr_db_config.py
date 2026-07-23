from __future__ import annotations

import unittest

from cbr_trading.db_config import (
    resolve_admin_database_selection,
    resolve_database_selection,
)
from cbr_trading.settings import CbrSettings


class DatabaseSelectionTests(unittest.TestCase):
    def test_defaults_to_external_urls_off_render(self) -> None:
        env = {
            "DATABASE_URL_SERVER_INT": "postgresql://primary-int",
            "DATABASE_URL_SERVER_EXT": "postgresql://primary-ext",
            "ANALYTICS_DATABASE_URL_SERVER_INT": (
                "postgresql://analytics-int"
            ),
            "ANALYTICS_DATABASE_URL_SERVER_EXT": (
                "postgresql://analytics-ext"
            ),
        }

        primary = resolve_database_selection("primary", env)
        analytics = resolve_database_selection("analytics", env)

        self.assertEqual(primary.target, "server_ext")
        self.assertEqual(primary.source, "DATABASE_URL_SERVER_EXT")
        self.assertEqual(primary.url, "postgresql://primary-ext")
        self.assertEqual(analytics.target, "server_ext")
        self.assertEqual(
            analytics.source,
            "ANALYTICS_DATABASE_URL_SERVER_EXT",
        )
        self.assertEqual(analytics.url, "postgresql://analytics-ext")

    def test_render_uses_internal_urls(self) -> None:
        env = {
            "CBR_ON_RENDER": "1",
            "DATABASE_URL_SERVER_INT": "postgresql://primary-int",
            "DATABASE_URL_SERVER_EXT": "postgresql://primary-ext",
            "ANALYTICS_DATABASE_URL_SERVER_INT": (
                "postgresql://analytics-int"
            ),
            "ANALYTICS_DATABASE_URL_SERVER_EXT": (
                "postgresql://analytics-ext"
            ),
        }

        primary = resolve_database_selection("primary", env)
        analytics = resolve_database_selection("analytics", env)

        self.assertEqual(primary.target, "server_int")
        self.assertEqual(primary.url, "postgresql://primary-int")
        self.assertEqual(analytics.target, "server_int")
        self.assertEqual(analytics.url, "postgresql://analytics-int")

    def test_explicit_cbr_flag_overrides_legacy_server_flag(self) -> None:
        selection = resolve_database_selection(
            "primary",
            {
                "CBR_ON_RENDER": "0",
                "SERVER": "true",
                "DATABASE_URL_SERVER_INT": "postgresql://internal",
                "DATABASE_URL_SERVER_EXT": "postgresql://external",
            },
        )
        self.assertEqual(selection.target, "server_ext")
        self.assertEqual(selection.url, "postgresql://external")

    def test_direct_role_urls_have_highest_priority(self) -> None:
        primary = resolve_database_selection(
            "primary",
            {
                "CBR_ON_RENDER": "1",
                "CBR_DATABASE_URL": "postgresql://primary-direct",
                "DATABASE_URL_SERVER_INT": "postgresql://internal",
            },
        )
        analytics = resolve_database_selection(
            "analytics",
            {
                "CBR_ANALYTICS_DATABASE_URL": (
                    "postgresql://analytics-direct"
                ),
                "ANALYTICS_DATABASE_URL_SERVER_EXT": (
                    "postgresql://external"
                ),
            },
        )
        self.assertEqual(primary.target, "url")
        self.assertEqual(primary.source, "CBR_DATABASE_URL")
        self.assertEqual(analytics.target, "url")
        self.assertEqual(
            analytics.source,
            "CBR_ANALYTICS_DATABASE_URL",
        )

    def test_explicit_targets_override_environment_default(self) -> None:
        primary = resolve_database_selection(
            "primary",
            {
                "CBR_ON_RENDER": "0",
                "PRIMARY_DB_TARGET": "local",
                "DATABASE_URL_LOCAL": "postgresql://local",
                "DATABASE_URL_SERVER_EXT": "postgresql://external",
            },
        )
        self.assertEqual(primary.target, "local")
        self.assertEqual(primary.url, "postgresql://local")

    def test_admin_url_overrides_then_falls_back_to_primary(self) -> None:
        explicit = resolve_admin_database_selection(
            {
                "CBR_ADMIN_DATABASE_URL": "postgresql://admin",
                "DATABASE_URL_SERVER_EXT": "postgresql://external",
            }
        )
        fallback = resolve_admin_database_selection(
            {"DATABASE_URL_SERVER_EXT": "postgresql://external"}
        )

        self.assertEqual(explicit.source, "CBR_ADMIN_DATABASE_URL")
        self.assertEqual(explicit.url, "postgresql://admin")
        self.assertEqual(fallback.source, "DATABASE_URL_SERVER_EXT")
        self.assertEqual(fallback.url, "postgresql://external")

    def test_secrets_are_hidden_from_repr(self) -> None:
        selection = resolve_database_selection(
            "primary",
            {"CBR_DATABASE_URL": "postgresql://user:secret@db/app"},
        )
        self.assertNotIn("secret", repr(selection))


class DatabaseSettingsTests(unittest.TestCase):
    def test_settings_expose_both_selected_roles_without_secrets(
        self,
    ) -> None:
        settings = CbrSettings.from_env(
            {
                "DATABASE_URL_SERVER_EXT": (
                    "postgresql://user:primary-secret@db/primary"
                ),
                "ANALYTICS_DATABASE_URL_SERVER_EXT": (
                    "postgresql://user:analytics-secret@db/analytics"
                ),
            }
        )

        self.assertEqual(
            settings.primary_database_source,
            "DATABASE_URL_SERVER_EXT",
        )
        self.assertEqual(
            settings.analytics_database_source,
            "ANALYTICS_DATABASE_URL_SERVER_EXT",
        )
        self.assertIn("primary-secret", settings.rules_database_url or "")
        self.assertIn(
            "analytics-secret",
            settings.analytics_database_url or "",
        )
        self.assertNotIn("primary-secret", repr(settings))
        self.assertNotIn("analytics-secret", repr(settings))


if __name__ == "__main__":
    unittest.main()
