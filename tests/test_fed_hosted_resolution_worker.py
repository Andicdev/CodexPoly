from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cbr_trading.domain import (
    ExecutionStatus,
    OrderExecutionResult,
    RepriceOnTickChange,
)
from cbr_trading.execution import (
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
)
from cbr_trading.fed import (
    FedOfficialObservation,
    FedRateDecision,
    fed_july_2026_decision_spec,
    fed_july_2026_market_bindings,
)
from cbr_trading.orchestration import ResolutionExecutionProfile
from cbr_trading.resolution_hosted import (
    FedHostedResolutionWorker,
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.sources import FED_SOURCE_NAME


_NOW = datetime(2026, 7, 29, 18, tzinfo=timezone.utc)


class _ProfileStore:
    def __init__(
        self,
        profiles: tuple[ResolutionExecutionProfile, ...],
    ):
        self._profiles = profiles
        self.ready_checks = 0
        self.loaded_sources: list[str | None] = []

    def set_profiles(
        self,
        profiles: tuple[ResolutionExecutionProfile, ...],
    ) -> None:
        self._profiles = profiles

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def load_enabled(
        self,
        *,
        source_name: str | None = None,
    ) -> tuple[ResolutionExecutionProfile, ...]:
        self.loaded_sources.append(source_name)
        return self._profiles


class _Poller:
    def __init__(
        self,
        observation: FedOfficialObservation | None,
    ):
        self.observation = observation
        self.polls = 0
        self.closed = False

    def poll_once(self) -> FedOfficialObservation | None:
        self.polls += 1
        return self.observation

    def close(self) -> None:
        self.closed = True


class _Outbox:
    def __init__(self) -> None:
        self.ready_checks = 0
        self.notifications: list[object] = []

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def enqueue(self, notification: object) -> None:
        self.notifications.append(notification)


class _LifecycleStore:
    def __init__(self) -> None:
        self.ready_checks = 0
        self.completed: list[tuple[str, str]] = []

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def complete_active_profile(
        self,
        *,
        profile_key: str,
        reason_code: str,
    ) -> None:
        self.completed.append((profile_key, reason_code))


class _RecordingExecutor:
    def __init__(self) -> None:
        self.prepared_templates: tuple[object, ...] = ()
        self.execute_calls: list[tuple[object, ...]] = []
        self.closed = False

    def prepare(self, templates, *, context):
        self.prepared_templates = tuple(templates)
        return PreparationSummary(
            items=tuple(
                PreparationItem(
                    template_id=template.template_id,
                    status=PreparationStatus.READY,
                    prepared_key=f"prepared:{template.template_id}",
                )
                for template in self.prepared_templates
            ),
            context=context,
        )

    def execute(self, intents, *, signal):
        del signal
        intent_rows = tuple(intents)
        self.execute_calls.append(intent_rows)
        return tuple(
            OrderExecutionResult(
                intent=intent,
                status=ExecutionStatus.DRY_RUN,
                attempted=False,
            )
            for intent in intent_rows
        )

    def close(self) -> None:
        self.closed = True


def _profiles() -> tuple[ResolutionExecutionProfile, ...]:
    return tuple(
        ResolutionExecutionProfile(
            profile_key=f"hosted-{binding.rule_key}",
            scope_id=binding.scope_id,
            source_name=FED_SOURCE_NAME,
            source_reference=binding.source_reference,
            account_name="test-account",
            condition_id=binding.condition_id,
            yes_desired_price=Decimal("0.999"),
            no_desired_price=Decimal("0.999"),
            quantity=Decimal("50"),
            prepare_from=_NOW - timedelta(minutes=5),
            expires_at=_NOW + timedelta(minutes=15),
            lifecycle_policy=RepriceOnTickChange(
                old_tick=Decimal("0.01"),
                new_tick=Decimal("0.001"),
                max_reprices=1,
            ),
            metadata={"rule_key": binding.rule_key},
        )
        for binding in fed_july_2026_market_bindings()
    )


def _observation() -> FedOfficialObservation:
    spec = fed_july_2026_decision_spec()
    return FedOfficialObservation(
        provider="fed_board_statement_html",
        source_url=spec.board_statement_url,
        decision=FedRateDecision(
            lower=Decimal("3.50"),
            upper=Decimal("3.75"),
        ),
        detected_at=_NOW,
        document_fingerprint="b" * 64,
        excerpt="target range for the federal funds rate",
    )


def _settings(
    *,
    mode: HostedResolutionMode = HostedResolutionMode.SHADOW,
) -> HostedResolutionSettings:
    return HostedResolutionSettings(
        mode=mode,
        database_url="postgresql://unused",
    )


class FedHostedResolutionWorkerTests(unittest.TestCase):
    def test_source_loop_is_hot_only_while_armed(self) -> None:
        worker = FedHostedResolutionWorker(
            settings=_settings(),
            profile_store=_ProfileStore(_profiles()),
            poller=_Poller(_observation()),
            clock=lambda: _NOW,
        )

        worker.prepare()
        self.assertEqual(worker._next_loop_delay(), 0.01)
        worker.poll_once()
        self.assertEqual(worker._next_loop_delay(), 0.25)
        worker.close()

    def test_all_profiles_share_one_prepared_execution_batch(self) -> None:
        executor = _RecordingExecutor()
        factory_profiles: list[ResolutionExecutionProfile] = []
        worker = FedHostedResolutionWorker(
            settings=_settings(),
            profile_store=_ProfileStore(_profiles()),
            lifecycle_store=_LifecycleStore(),
            poller=_Poller(_observation()),
            executor_factory=lambda profile: (
                factory_profiles.append(profile) or executor
            ),
            clock=lambda: _NOW,
        )

        preparations = worker.prepare()
        result = worker.poll_once()

        self.assertEqual(len(preparations), 5)
        self.assertEqual(len(factory_profiles), 1)
        self.assertEqual(len(executor.prepared_templates), 10)
        self.assertEqual(len(executor.execute_calls), 1)
        self.assertEqual(len(executor.execute_calls[0]), 5)
        self.assertEqual(result.completed_count, 5)
        self.assertEqual(
            {
                intent.outcome.value
                for intent in executor.execute_calls[0]
            },
            {"YES", "NO"},
        )
        worker.close()
        self.assertTrue(executor.closed)

    def test_one_observation_completes_all_five_markets(self) -> None:
        poller = _Poller(_observation())
        outbox = _Outbox()
        profiles = _ProfileStore(_profiles())
        lifecycle = _LifecycleStore()
        worker = FedHostedResolutionWorker(
            settings=_settings(),
            profile_store=profiles,
            lifecycle_store=lifecycle,
            notification_outbox=outbox,
            poller=poller,
            clock=lambda: _NOW,
        )

        preparations = worker.prepare()
        result = worker.poll_once()

        self.assertEqual(len(preparations), 5)
        self.assertTrue(all(row.ready for row in preparations))
        self.assertTrue(
            all(row.template_count == 2 for row in preparations)
        )
        self.assertEqual(result.fact_count, 1)
        self.assertEqual(result.completed_count, 5)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(poller.polls, 1)
        self.assertEqual(len(outbox.notifications), 1)
        self.assertEqual(
            profiles.loaded_sources,
            [FED_SOURCE_NAME],
        )
        self.assertEqual(
            lifecycle.completed,
            [
                (
                    profile.profile_key,
                    "resolution_execution_completed",
                )
                for profile in _profiles()
            ],
        )
        worker.close()
        self.assertTrue(poller.closed)

    def test_no_enabled_profiles_do_not_poll_public_sources(self) -> None:
        poller = _Poller(_observation())
        worker = FedHostedResolutionWorker(
            settings=_settings(),
            profile_store=_ProfileStore(()),
            poller=poller,
        )

        self.assertEqual(worker.prepare(), ())
        result = worker.poll_once()

        self.assertEqual(result.fact_count, 0)
        self.assertEqual(poller.polls, 0)
        worker.close()

    def test_condition_mismatch_fails_before_polling(self) -> None:
        profiles = _profiles()
        bad = replace(
            profiles[0],
            condition_id="0x" + "0" * 64,
        )
        poller = _Poller(None)
        worker = FedHostedResolutionWorker(
            settings=_settings(),
            profile_store=_ProfileStore((bad,)),
            poller=poller,
        )

        with self.assertRaisesRegex(RuntimeError, "condition_id"):
            worker.prepare()
        self.assertEqual(poller.polls, 0)

    def test_market_url_mismatch_fails_before_polling(self) -> None:
        profiles = _profiles()
        bad = replace(
            profiles[0],
            source_reference="https://polymarket.com/event/wrong",
        )
        worker = FedHostedResolutionWorker(
            settings=_settings(),
            profile_store=_ProfileStore((bad,)),
            poller=_Poller(None),
        )

        with self.assertRaisesRegex(RuntimeError, "source_reference"):
            worker.prepare()

    def test_live_reprice_requires_supervision_before_executor(self) -> None:
        worker = FedHostedResolutionWorker(
            settings=_settings(mode=HostedResolutionMode.LIVE),
            profile_store=_ProfileStore(_profiles()),
            poller=_Poller(None),
            executor_factory=lambda _profile: self.fail(
                "executor must not be constructed"
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "RESOLUTION_SUPERVISION_ENABLED",
        ):
            worker.prepare()

    def test_reconcile_attaches_and_detaches_without_restart(self) -> None:
        profiles = _ProfileStore(())
        worker = FedHostedResolutionWorker(
            settings=_settings(),
            profile_store=profiles,
            poller=_Poller(None),
            clock=lambda: _NOW,
        )

        self.assertEqual(worker.reconcile_profiles(), ())
        profiles.set_profiles((_profiles()[0],))
        attached = worker.reconcile_profiles()
        self.assertEqual(len(attached), 1)
        self.assertEqual(worker.managed_count, 1)

        profiles.set_profiles(())
        self.assertEqual(worker.reconcile_profiles(), ())
        self.assertEqual(worker.managed_count, 0)
        worker.close()

    def test_checked_in_bindings_cover_all_five_buckets(self) -> None:
        bindings = fed_july_2026_market_bindings()

        self.assertEqual(len(bindings), 5)
        self.assertEqual(
            {binding.bucket.value for binding in bindings},
            {
                "decrease_50_plus",
                "decrease_25",
                "no_change",
                "increase_25",
                "increase_50_plus",
            },
        )
        self.assertTrue(
            all(len(binding.condition_id) == 66 for binding in bindings)
        )


if __name__ == "__main__":
    unittest.main()
