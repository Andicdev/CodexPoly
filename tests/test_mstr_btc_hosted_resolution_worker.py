from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cbr_trading.domain import RepriceOnTickChange
from cbr_trading.mstr_btc import (
    MSTR_JUL21_27_SCOPE_ID,
    MstrBtcFactCandidate,
    MstrBtcProvider,
    MstrBtcValueDerivation,
    mstr_jul21_27_market_bindings,
    mstr_jul21_27_resolution_rules,
)
from cbr_trading.orchestration import ResolutionExecutionProfile
from cbr_trading.resolution_hosted import (
    HostedResolutionMode,
    HostedResolutionSettings,
    MstrBtcHostedResolutionWorker,
)
from cbr_trading.sources import MSTR_BTC_SOURCE_NAME


_NOW = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)


class _AuditStore:
    def __init__(self, facts: tuple[MstrBtcFactCandidate, ...]):
        self._facts = facts
        self.ready_checks = 0
        self.loaded_scopes: list[str | None] = []

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def load_validated_facts(
        self,
        *,
        scope_id: str | None = None,
    ) -> tuple[MstrBtcFactCandidate, ...]:
        self.loaded_scopes.append(scope_id)
        return tuple(
            fact
            for fact in self._facts
            if scope_id is None or fact.scope_id == scope_id
        )


class _ProfileStore:
    def __init__(self, profiles: tuple[ResolutionExecutionProfile, ...]):
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


def _profiles() -> tuple[ResolutionExecutionProfile, ...]:
    bindings = mstr_jul21_27_market_bindings()
    return tuple(
        ResolutionExecutionProfile(
            profile_key=f"hosted-test-{binding.rule_key}",
            scope_id=binding.signal_id,
            source_name=MSTR_BTC_SOURCE_NAME,
            source_reference=binding.source_reference,
            account_name="test-account",
            condition_id=binding.condition_id,
            yes_desired_price=Decimal("0.999"),
            no_desired_price=Decimal("0.999"),
            quantity=Decimal("50"),
            prepare_from=_NOW - timedelta(hours=1),
            expires_at=_NOW + timedelta(hours=16),
            lifecycle_policy=RepriceOnTickChange(
                old_tick=Decimal("0.01"),
                new_tick=Decimal("0.001"),
                max_reprices=1,
            ),
            metadata={"rule_key": binding.rule_key},
        )
        for binding in bindings
    )


def _fact() -> MstrBtcFactCandidate:
    return MstrBtcFactCandidate(
        scope_id=MSTR_JUL21_27_SCOPE_ID,
        provider=MstrBtcProvider.SEC,
        provider_event_id="hosted-test-filing",
        baseline_state_id="42",
        holdings_before_btc=843_775,
        holdings_after_btc=845_275,
        net_change_btc=1_500,
        acquired_btc=1_500,
        sold_btc=None,
        acquired_derivation=MstrBtcValueDerivation.EXPLICIT,
        sold_derivation=MstrBtcValueDerivation.NOT_CONFIRMED,
        holdings_crosscheck_difference_btc=0,
        source_url="https://www.sec.gov/hosted-test.htm",
        filing_url="https://www.sec.gov/hosted-test-index.htm",
        published_at=_NOW,
        detected_at=_NOW + timedelta(seconds=2),
        parser_name="hosted_test",
        parser_version="1",
        document_fingerprint="hosted-test-fingerprint",
        evidence_excerpts=("Aggregate BTC Holdings",),
        attributes={"ticker": "MSTR", "cik": "1050446"},
    )


def _settings(
    *,
    mode: HostedResolutionMode = HostedResolutionMode.SHADOW,
    supervision_enabled: bool = False,
) -> HostedResolutionSettings:
    return HostedResolutionSettings(
        mode=mode,
        database_url="postgresql://unused",
        supervision_enabled=supervision_enabled,
    )


class MstrBtcHostedResolutionWorkerTests(unittest.TestCase):
    def test_three_profiles_complete_from_one_persisted_fact(self) -> None:
        audit = _AuditStore((_fact(),))
        profiles = _ProfileStore(_profiles())
        lifecycle = _LifecycleStore()
        worker = MstrBtcHostedResolutionWorker(
            settings=_settings(),
            audit_store=audit,
            profile_store=profiles,
            lifecycle_store=lifecycle,
            clock=lambda: _NOW,
        )

        preparations = worker.prepare()
        result = worker.poll_once()

        self.assertEqual(len(preparations), 3)
        self.assertTrue(all(row.ready for row in preparations))
        self.assertTrue(
            all(row.template_count == 2 for row in preparations)
        )
        self.assertEqual(worker.managed_count, 3)
        self.assertEqual(result.fact_count, 1)
        self.assertEqual(result.completed_count, 3)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(
            audit.loaded_scopes,
            [MSTR_JUL21_27_SCOPE_ID],
        )
        self.assertEqual(
            profiles.loaded_sources,
            [MSTR_BTC_SOURCE_NAME],
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

    def test_disabled_profile_set_leaves_worker_unprepared(self) -> None:
        audit = _AuditStore((_fact(),))
        worker = MstrBtcHostedResolutionWorker(
            settings=_settings(),
            audit_store=audit,
            profile_store=_ProfileStore(()),
        )

        self.assertEqual(worker.prepare(), ())
        self.assertEqual(worker.managed_count, 0)
        self.assertEqual(audit.loaded_scopes, [])
        worker.close()

    def test_condition_mismatch_fails_before_polling(self) -> None:
        profiles = _profiles()
        bad = replace(
            profiles[0],
            condition_id="0x" + "0" * 64,
        )
        worker = MstrBtcHostedResolutionWorker(
            settings=_settings(),
            audit_store=_AuditStore(()),
            profile_store=_ProfileStore((bad,)),
        )

        with self.assertRaisesRegex(RuntimeError, "condition_id"):
            worker.prepare()

    def test_market_url_mismatch_fails_before_polling(self) -> None:
        profiles = _profiles()
        bad = replace(
            profiles[0],
            source_reference="https://polymarket.com/event/wrong",
        )
        worker = MstrBtcHostedResolutionWorker(
            settings=_settings(),
            audit_store=_AuditStore(()),
            profile_store=_ProfileStore((bad,)),
        )

        with self.assertRaisesRegex(RuntimeError, "source_reference"):
            worker.prepare()

    def test_expired_profiles_never_consume_fact(self) -> None:
        worker = MstrBtcHostedResolutionWorker(
            settings=_settings(),
            audit_store=_AuditStore((_fact(),)),
            profile_store=_ProfileStore(_profiles()),
            clock=lambda: _NOW + timedelta(days=1),
        )

        worker.prepare()
        result = worker.poll_once()

        self.assertEqual(result.completed_count, 0)
        self.assertEqual(result.expired_count, 3)
        self.assertEqual(result.failed_count, 0)
        worker.close()

    def test_live_reprice_requires_supervision_before_executor(self) -> None:
        worker = MstrBtcHostedResolutionWorker(
            settings=_settings(mode=HostedResolutionMode.LIVE),
            audit_store=_AuditStore(()),
            profile_store=_ProfileStore(_profiles()),
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
        worker = MstrBtcHostedResolutionWorker(
            settings=_settings(),
            audit_store=_AuditStore(()),
            profile_store=profiles,
            clock=lambda: _NOW,
        )

        self.assertEqual(worker.reconcile_profiles(), ())
        profiles.set_profiles((_profiles()[0],))
        attached = worker.reconcile_profiles()
        self.assertEqual(len(attached), 1)
        self.assertEqual(worker.managed_count, 1)
        self.assertEqual(worker.reconcile_profiles(), ())
        self.assertEqual(worker.managed_count, 1)

        profiles.set_profiles(())
        self.assertEqual(worker.reconcile_profiles(), ())
        self.assertEqual(worker.managed_count, 0)
        worker.close()

    def test_checked_in_market_bindings_match_source_rules(self) -> None:
        rules = {
            rule.signal_id: rule
            for rule in mstr_jul21_27_resolution_rules()
        }
        bindings = mstr_jul21_27_market_bindings()

        self.assertEqual(len(bindings), 3)
        self.assertEqual(
            {binding.signal_id for binding in bindings},
            set(rules),
        )
        for binding in bindings:
            self.assertEqual(
                binding.rule_key,
                rules[binding.signal_id].rule_key,
            )
            self.assertEqual(len(binding.condition_id), 66)
            self.assertTrue(
                binding.source_reference.startswith(
                    "https://polymarket.com/event/"
                )
            )


if __name__ == "__main__":
    unittest.main()
