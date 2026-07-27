from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from cbr_trading.domain import RepriceOnTickChange
from cbr_trading.execution import (
    PreparationContext,
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.notifications import (
    source_event_notification_from_profile_lifecycle,
)
from cbr_trading.orchestration import ResolutionExecutionProfile
from cbr_trading.profile_lifecycle.contracts import (
    ProfileAutomationMode,
    ProfilePreflightClaim,
    ProfileScheduleState,
    ProfileScheduleTransition,
    ResolutionProfileSchedule,
)
from cbr_trading.profile_lifecycle.controller import (
    ProfileLifecycleController,
)
from cbr_trading.profile_lifecycle.readiness import (
    ProfileReadinessWorker,
)
from cbr_trading.profile_lifecycle.settings import (
    ProfileLifecycleSettings,
    ProfileReadinessSettings,
)


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "012_add_resolution_profile_schedules.sql"
)
_NOW = datetime(2026, 7, 28, 8, 45, tzinfo=timezone.utc)


def _transition(
    state: ProfileScheduleState,
    *,
    event_id: int = 1,
) -> ProfileScheduleTransition:
    return ProfileScheduleTransition(
        event_id=event_id,
        event_key=f"profile-lifecycle:schedule:{state.value.lower()}",
        schedule_key="schedule:earnings-hlt-2026q2",
        profile_key="earnings-hlt-2026q2",
        scope_id="earnings:HLT:2026Q2",
        source_reference="https://polymarket.com/event/hlt-eps",
        automation_mode=ProfileAutomationMode.AUTO_PREFLIGHT,
        previous_state=ProfileScheduleState.PREFLIGHTING,
        next_state=state,
        event_kind=f"TEST_{state.value}",
        reason_code=(
            "authenticated_preflight_not_ready"
            if state is ProfileScheduleState.BLOCKED
            else None
        ),
        activate_at=_NOW + timedelta(minutes=15),
        deactivate_at=_NOW + timedelta(hours=8),
    )


class ProfileLifecycleContractTests(unittest.TestCase):
    def test_schedule_normalizes_times_and_mode(self) -> None:
        schedule = ResolutionProfileSchedule(
            schedule_key="schedule:test",
            profile_key="profile:test",
            automation_mode=ProfileAutomationMode.AUTO_PREFLIGHT,
            preflight_at=_NOW,
            activate_at=_NOW + timedelta(minutes=15),
            deactivate_at=_NOW + timedelta(hours=1),
        )

        self.assertEqual(
            schedule.automation_mode,
            ProfileAutomationMode.AUTO_PREFLIGHT,
        )
        self.assertEqual(schedule.preflight_at.tzinfo, timezone.utc)

    def test_auto_live_is_disabled_by_default_and_requires_cap(self) -> None:
        settings = ProfileLifecycleSettings.from_env(
            {"CBR_DATABASE_URL": "postgresql://configured"}
        )
        self.assertFalse(settings.auto_live_enabled)

        with self.assertRaisesRegex(
            ValueError,
            "MAX_TOTAL_NOTIONAL",
        ):
            ProfileLifecycleSettings.from_env(
                {
                    "CBR_DATABASE_URL": "postgresql://configured",
                    "PROFILE_SCHEDULER_AUTO_LIVE_ENABLED": "1",
                }
            )

    def test_migration_is_additive_and_keeps_profile_table_unchanged(
        self,
    ) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8")
        statements = "\n".join(
            line
            for line in sql.splitlines()
            if not line.lstrip().startswith("--")
        ).upper()

        self.assertNotIn("ALTER TABLE", statements)
        self.assertNotIn("DROP TABLE", statements)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS RESOLUTION_PROFILE_SCHEDULES",
            statements,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS "
            "RESOLUTION_PROFILE_SCHEDULE_EVENTS",
            statements,
        )
        self.assertIn("'AUTO_PREFLIGHT'", statements)
        self.assertIn("'AUTO_LIVE'", statements)

    def test_enabled_notification_states_eligibility_precisely(self) -> None:
        transition = ProfileScheduleTransition(
            **{
                **_transition(ProfileScheduleState.ACTIVE).__dict__,
                "automation_mode": ProfileAutomationMode.AUTO_LIVE,
            }
        )

        notification = (
            source_event_notification_from_profile_lifecycle(
                transition
            )
        )

        self.assertIn(
            "CodexPoly: Profile enabled",
            notification.message_text,
        )
        self.assertIn(
            "Profile status is ENABLED",
            notification.message_text,
        )
        self.assertIn(
            "https://polymarket.com/event/hlt-eps",
            notification.message_text,
        )


class _LifecycleStore:
    def __init__(self):
        self.requests = [_transition(ProfileScheduleState.PREFLIGHTING)]
        self.events = list(self.requests)
        self.calls = []

    def expire_due(self, *, now):
        self.calls.append("expire")
        return None

    def block_due_unready(self, *, now, grace_seconds):
        self.calls.append("block")
        return None

    def request_due_preflight(self, *, now):
        self.calls.append("request")
        return self.requests.pop(0) if self.requests else None

    def activate_due_ready(
        self,
        *,
        now,
        max_total_notional,
        live_heartbeat_stale_seconds,
        activation_grace_seconds,
    ):
        self.calls.append("activate")
        return None

    def load_unnotified_event(self):
        return self.events.pop(0) if self.events else None

    def mark_event_notified(self, event_id):
        self.calls.append(("notified", event_id))


class _NotificationOutbox:
    def __init__(self):
        self.notifications = []

    def enqueue(self, notification, *, delivery_delay_seconds=0):
        self.notifications.append(notification)


class ProfileLifecycleControllerTests(unittest.TestCase):
    def test_auto_preflight_requests_and_notifies_but_never_activates(
        self,
    ) -> None:
        store = _LifecycleStore()
        outbox = _NotificationOutbox()
        controller = ProfileLifecycleController(
            settings=ProfileLifecycleSettings(
                database_url="postgresql://configured",
                auto_live_enabled=False,
                batch_size=10,
            ),
            store=store,
            notification_outbox=outbox,
            clock=lambda: _NOW,
        )

        result = controller.run_once()

        self.assertEqual(result.preflight_requested, 1)
        self.assertEqual(result.activated, 0)
        self.assertNotIn("activate", store.calls)
        self.assertEqual(len(outbox.notifications), 1)
        self.assertIn(
            "Profile status remains DISABLED",
            outbox.notifications[0].message_text,
        )


def _profile() -> ResolutionExecutionProfile:
    return ResolutionExecutionProfile(
        profile_key="earnings-hlt-2026q2",
        scope_id="earnings:HLT:2026Q2",
        source_name="earnings_resolution",
        source_reference="https://polymarket.com/event/hlt-eps",
        account_name="account",
        condition_id="0xcondition",
        yes_desired_price=Decimal("0.999"),
        no_desired_price=Decimal("0.999"),
        quantity=Decimal("50"),
        prepare_from=_NOW + timedelta(minutes=15),
        expires_at=_NOW + timedelta(hours=8),
        lifecycle_policy=RepriceOnTickChange(
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
        ),
        metadata={"rule_key": "hlt-rule"},
    )


class _ReadinessStore:
    def __init__(self):
        self.claim = ProfilePreflightClaim(
            schedule_key="schedule:earnings-hlt-2026q2",
            profile_key="earnings-hlt-2026q2",
            request_id="request",
            activate_at=_NOW + timedelta(minutes=15),
            deactivate_at=_NOW + timedelta(hours=8),
        )
        self.completed = []
        self.failed = []

    def claim_preflight(self, *, now, lease_seconds):
        claim, self.claim = self.claim, None
        return claim

    def complete_preflight(self, claim, **kwargs):
        self.completed.append((claim, kwargs))

    def fail_preflight(self, claim, **kwargs):
        self.failed.append((claim, kwargs))


class _ProfileStore:
    def load(self, profile_key):
        return _profile()


@dataclass(frozen=True)
class _Detail:
    order_presigned: bool = True


class _PreflightExecutor:
    def __init__(self):
        self.details = (_Detail(), _Detail())
        self.maximum_notional = Decimal("99.9")
        self.closed = False

    def prepare(self, templates, *, context: PreparationContext):
        return PreparationSummary(
            items=tuple(
                PreparationItem(
                    template_id=template.template_id,
                    status=PreparationStatus.READY,
                    prepared_key=f"prepared:{template.template_id}",
                )
                for template in templates
            ),
            context=context,
        )

    def close(self):
        self.closed = True


class ProfileReadinessWorkerTests(unittest.TestCase):
    def test_authenticated_preflight_records_ready_without_execute(
        self,
    ) -> None:
        store = _ReadinessStore()
        executor = _PreflightExecutor()
        worker = ProfileReadinessWorker(
            settings=ProfileReadinessSettings(
                database_url="postgresql://configured",
                readiness_ttl_seconds=1_800,
            ),
            store=store,
            profile_store=_ProfileStore(),
            safety=LiveSafetySettings(),
            executor_factory=lambda profile: executor,
            clock=lambda: _NOW,
        )

        processed = worker.run_once()

        self.assertTrue(processed)
        self.assertEqual(len(store.completed), 1)
        self.assertEqual(store.failed, [])
        evidence = store.completed[0][1]["evidence"]
        self.assertTrue(evidence["all_presigned"])
        self.assertEqual(evidence["template_count"], 2)
        self.assertTrue(executor.closed)


if __name__ == "__main__":
    unittest.main()
