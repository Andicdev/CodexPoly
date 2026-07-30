from __future__ import annotations

import logging
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from cbr_trading.application import CoordinationStatus
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
from cbr_trading.profile_lifecycle.repository import (
    SqlAlchemyProfileLifecycleStore,
    _SELECT_DUE_EXPIRY_SQL,
)
from cbr_trading.profile_lifecycle.settings import (
    ProfileLifecycleSettings,
    ProfileReadinessSettings,
)
from cbr_trading.resolution_hosted.lifecycle import (
    block_terminal_profile_failure,
)


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "012_add_resolution_profile_schedules.sql"
)
_COMPLETION_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "017_add_completed_profile_schedule_state.sql"
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
        self.assertIn("'COMPLETED'", statements)

    def test_completion_migration_only_expands_lifecycle_states(
        self,
    ) -> None:
        statements = _COMPLETION_MIGRATION.read_text(
            encoding="utf-8"
        ).upper()

        self.assertNotIn("DROP TABLE", statements)
        self.assertNotIn("DROP COLUMN", statements)
        self.assertIn("ALTER TABLE RESOLUTION_PROFILE_SCHEDULES", statements)
        self.assertIn(
            "ALTER TABLE RESOLUTION_PROFILE_SCHEDULE_EVENTS",
            statements,
        )
        self.assertGreaterEqual(statements.count("'COMPLETED'"), 3)

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

    def test_pending_notification_is_supported_for_manual_rearm(self) -> None:
        notification = source_event_notification_from_profile_lifecycle(
            _transition(ProfileScheduleState.PENDING)
        )

        self.assertIn(
            "CodexPoly: Profile returned to pending",
            notification.message_text,
        )
        self.assertIn(
            "authenticated preflight is pending",
            notification.message_text,
        )

    def test_completed_notification_preserves_existing_orders(self) -> None:
        notification = source_event_notification_from_profile_lifecycle(
            _transition(ProfileScheduleState.COMPLETED)
        )

        self.assertIn(
            "CodexPoly: Profile resolution completed",
            notification.message_text,
        )
        self.assertIn(
            "Profile status is DISABLED for new signals",
            notification.message_text,
        )
        self.assertIn(
            "Existing submitted orders are left unchanged",
            notification.message_text,
        )

    def test_terminal_failure_notification_is_not_activation_failure(
        self,
    ) -> None:
        transition = ProfileScheduleTransition(
            **{
                **_transition(ProfileScheduleState.BLOCKED).__dict__,
                "event_kind": "RESOLUTION_PROCESSING_BLOCKED",
                "reason_code": "live_execution_failed",
            }
        )

        notification = source_event_notification_from_profile_lifecycle(
            transition
        )

        self.assertIn(
            "CodexPoly: Profile resolution blocked",
            notification.message_text,
        )
        self.assertIn(
            "Profile status is DISABLED for new signals",
            notification.message_text,
        )
        self.assertNotIn(
            "Profile activation blocked",
            notification.message_text,
        )

    def test_terminal_failures_have_specific_safe_reason_codes(
        self,
    ) -> None:
        class Store:
            def __init__(self) -> None:
                self.calls = []

            def block_active_profile(self, **kwargs) -> None:
                self.calls.append(kwargs)

        store = Store()
        expected = {
            CoordinationStatus.SOURCE_ERROR: (
                "live_source_contract_failed"
            ),
            CoordinationStatus.STRATEGY_ERROR: (
                "live_strategy_evaluation_failed"
            ),
            CoordinationStatus.EXECUTION_ERROR: (
                "live_execution_failed"
            ),
        }

        for status, reason in expected.items():
            block_terminal_profile_failure(
                store,
                profile_key="profile:test",
                status=status,
                logger=logging.getLogger(__name__),
            )
            self.assertEqual(store.calls[-1]["reason_code"], reason)

    def test_terminal_failure_block_can_be_retried_safely(self) -> None:
        class FlakyStore:
            def __init__(self) -> None:
                self.attempts = 0

            def block_active_profile(self, **_kwargs) -> None:
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("temporary")

        store = FlakyStore()
        logger = logging.getLogger(__name__)

        first = block_terminal_profile_failure(
            store,
            profile_key="profile:test",
            status=CoordinationStatus.EXECUTION_ERROR,
            logger=logger,
        )
        second = block_terminal_profile_failure(
            store,
            profile_key="profile:test",
            status=CoordinationStatus.EXECUTION_ERROR,
            logger=logger,
        )

        self.assertFalse(first)
        self.assertTrue(second)
        self.assertEqual(store.attempts, 2)

    def test_expiry_never_overwrites_completed_state(self) -> None:
        self.assertIn(
            "schedule.state NOT IN "
            "('BLOCKED', 'COMPLETED', 'EXPIRED')",
            _SELECT_DUE_EXPIRY_SQL,
        )


class _DbResult:
    def __init__(self, *, one=None, one_or_none=None):
        self._one = one
        self._one_or_none = one_or_none

    def mappings(self):
        return self

    def one(self):
        return self._one

    def one_or_none(self):
        return self._one_or_none


class _DbSession:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return self.results.pop(0)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


class ProfileLifecycleRepositoryTests(unittest.TestCase):
    def test_completion_disables_profile_and_appends_terminal_event(
        self,
    ) -> None:
        row = {
            "id": 11,
            "schedule_key": "schedule:profile:test",
            "profile_key": "profile:test",
            "automation_mode": "AUTO_LIVE",
            "activate_at": _NOW - timedelta(minutes=5),
            "deactivate_at": _NOW + timedelta(hours=1),
            "scope_id": "earnings:TEST:2026Q2",
            "source_reference": (
                "https://polymarket.com/event/test-eps"
            ),
        }
        session = _DbSession(
            (
                _DbResult(one_or_none=row),
                _DbResult(),
                _DbResult(),
                _DbResult(one={"id": 12}),
            )
        )
        store = SqlAlchemyProfileLifecycleStore(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )

        transition = store.complete_active_profile(
            profile_key="profile:test"
        )

        assert transition is not None
        self.assertEqual(
            transition.previous_state,
            ProfileScheduleState.ACTIVE,
        )
        self.assertEqual(
            transition.next_state,
            ProfileScheduleState.COMPLETED,
        )
        self.assertEqual(
            transition.event_kind,
            "RESOLUTION_EXECUTION_COMPLETED",
        )
        self.assertEqual(session.commits, 1)
        self.assertIn("SET status = 'DISABLED'", session.calls[1][0])
        self.assertEqual(session.calls[2][1]["state"], "COMPLETED")
        self.assertIn(
            "existing_orders_left_unchanged",
            session.calls[3][1]["metadata"],
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
        self.deferred = []
        self.failed = []

    def claim_preflight(self, *, now, lease_seconds):
        claim, self.claim = self.claim, None
        return claim

    def complete_preflight(self, claim, **kwargs):
        self.completed.append((claim, kwargs))

    def fail_preflight(self, claim, **kwargs):
        self.failed.append((claim, kwargs))

    def defer_preflight(self, claim, **kwargs):
        self.deferred.append((claim, kwargs))


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


class _FailedPreflightExecutor(_PreflightExecutor):
    def prepare(self, templates, *, context: PreparationContext):
        return PreparationSummary(
            items=tuple(
                PreparationItem(
                    template_id=template.template_id,
                    status=PreparationStatus.FAILED,
                    error=(
                        "Authenticated preflight failed: "
                        "UnexpectedResponseError"
                    ),
                )
                for template in templates
            ),
            context=context,
        )


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
        self.assertEqual(store.deferred, [])
        self.assertEqual(store.failed, [])
        evidence = store.completed[0][1]["evidence"]
        self.assertTrue(evidence["all_presigned"])
        self.assertEqual(evidence["template_count"], 2)
        self.assertTrue(executor.closed)

    def test_transient_preflight_failure_is_deferred_for_retry(
        self,
    ) -> None:
        store = _ReadinessStore()
        executor = _FailedPreflightExecutor()
        worker = ProfileReadinessWorker(
            settings=ProfileReadinessSettings(
                database_url="postgresql://configured",
                retry_seconds=10,
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
        self.assertEqual(store.completed, [])
        self.assertEqual(store.failed, [])
        self.assertEqual(len(store.deferred), 1)
        deferred = store.deferred[0][1]
        self.assertEqual(
            deferred["error_code"],
            "preflight_transport_unavailable",
        )
        self.assertEqual(
            deferred["retry_at"],
            _NOW + timedelta(seconds=10),
        )
        self.assertTrue(executor.closed)


if __name__ == "__main__":
    unittest.main()
