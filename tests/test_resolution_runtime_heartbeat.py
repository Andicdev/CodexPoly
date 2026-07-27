from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cbr_trading.profile_lifecycle.repository import (
    _live_runtime_healthy,
)
from cbr_trading.resolution_hosted.runtime_repository import (
    SqlAlchemyResolutionRuntimeStore,
)
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionMode,
)


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "013_add_resolution_runtime_heartbeats.sql"
)
_NOW = datetime(2026, 7, 28, 8, 45, tzinfo=timezone.utc)


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one(self):
        return self._row


class _Session:
    def __init__(self):
        self.executions = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.executions.append((str(statement), params))
        if "to_regclass" in str(statement):
            return _Result(
                {
                    "heartbeat_table": True,
                    "heartbeat_columns": True,
                    "heartbeat_key_index": True,
                    "heartbeat_seen_index": True,
                }
            )
        return _Result({"id": 1})

    def commit(self):
        self.commits += 1


class ResolutionRuntimeHeartbeatTests(unittest.TestCase):
    def test_migration_is_additive(self) -> None:
        text = _MIGRATION.read_text(encoding="utf-8").upper()

        self.assertIn(
            "CREATE TABLE IF NOT EXISTS "
            "RESOLUTION_RUNTIME_HEARTBEATS",
            text,
        )
        self.assertNotIn("DROP TABLE", text)
        self.assertNotIn("ALTER TABLE", text)

    def test_store_persists_only_runtime_state(self) -> None:
        session = _Session()
        store = SqlAlchemyResolutionRuntimeStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        store.ensure_ready()
        store.heartbeat(
            runtime_key="hosted-resolution",
            mode=HostedResolutionMode.LIVE,
            supervision_enabled=True,
            trading_enabled=True,
            process_started_at=_NOW - timedelta(seconds=5),
            seen_at=_NOW,
            metadata={"profile_refresh": "dynamic"},
        )

        self.assertEqual(session.commits, 1)
        params = session.executions[-1][1]
        self.assertEqual(params["mode"], "live")
        self.assertTrue(params["supervision_enabled"])
        self.assertTrue(params["trading_enabled"])
        self.assertNotIn("secret", " ".join(params).casefold())

    def test_activation_gate_requires_fresh_fully_live_runtime(self) -> None:
        healthy = {
            "mode": "live",
            "supervision_enabled": True,
            "trading_enabled": True,
            "last_seen_at": _NOW - timedelta(seconds=5),
        }
        self.assertTrue(
            _live_runtime_healthy(
                healthy,
                now=_NOW,
                stale_seconds=15,
            )
        )
        for change in (
            {"mode": "shadow"},
            {"supervision_enabled": False},
            {"trading_enabled": False},
            {"last_seen_at": _NOW - timedelta(seconds=15)},
        ):
            self.assertFalse(
                _live_runtime_healthy(
                    {**healthy, **change},
                    now=_NOW,
                    stale_seconds=15,
                )
            )


if __name__ == "__main__":
    unittest.main()
