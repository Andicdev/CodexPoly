from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cbr_trading.domain import RepriceOnTickChange
from cbr_trading.earnings import (
    EarningsFactCandidate,
    EarningsProvider,
    SourceAuthority,
)
from cbr_trading.earnings.parsers import checked_in_shadow_rules
from cbr_trading.orchestration import ResolutionExecutionProfile
from cbr_trading.resolution_hosted import (
    EarningsHostedResolutionWorker,
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.sources.earnings import EARNINGS_SOURCE_NAME


_NOW = datetime(2026, 7, 27, 20, tzinfo=timezone.utc)


class _EarningsStore:
    def __init__(self, facts: tuple[EarningsFactCandidate, ...]):
        self._facts = facts
        self.ready_checks = 0

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def load_active_rules(self) -> tuple:
        return checked_in_shadow_rules()

    def load_validated_facts(self) -> tuple:
        return self._facts


class _ProfileStore:
    def __init__(self, profiles: tuple[ResolutionExecutionProfile, ...]):
        self._profiles = profiles
        self.ready_checks = 0

    def set_profiles(
        self,
        profiles: tuple[ResolutionExecutionProfile, ...],
    ) -> None:
        self._profiles = profiles

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def load_enabled(self, *, source_name: str | None = None) -> tuple:
        assert source_name == EARNINGS_SOURCE_NAME
        return self._profiles


class _LifecycleStore:
    def __init__(self) -> None:
        self.ready_checks = 0
        self.blocked: list[tuple[str, str]] = []
        self.completed: list[tuple[str, str]] = []

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def block_active_profile(
        self,
        *,
        profile_key: str,
        reason_code: str,
    ) -> None:
        self.blocked.append((profile_key, reason_code))

    def complete_active_profile(
        self,
        *,
        profile_key: str,
        reason_code: str,
    ) -> None:
        self.completed.append((profile_key, reason_code))


def _profile(rule: object) -> ResolutionExecutionProfile:
    return ResolutionExecutionProfile(
        profile_key=f"production-{rule.ticker.lower()}",
        scope_id=rule.scope_id,
        source_name=EARNINGS_SOURCE_NAME,
        source_reference=(
            f"https://polymarket.com/event/{rule.market_slug}"
        ),
        account_name="test-account",
        condition_id=rule.condition_id,
        yes_desired_price=Decimal("0.99"),
        no_desired_price=Decimal("0.99"),
        quantity=Decimal("5"),
        prepare_from=_NOW - timedelta(hours=1),
        expires_at=_NOW + timedelta(hours=6),
        lifecycle_policy=RepriceOnTickChange(
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
        ),
    )


def _fact(rule: object, value: str) -> EarningsFactCandidate:
    return EarningsFactCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=f"test-{rule.ticker}",
        ticker=rule.ticker,
        cik=rule.cik,
        period_end=rule.period_end,
        metric=rule.metric,
        basis=rule.primary_basis,
        currency=rule.currency,
        raw_value=Decimal(value),
        value=Decimal(value),
        authority=SourceAuthority.OFFICIAL_COMPANY,
        source_url=(
            f"https://www.sec.gov/test/{rule.ticker.lower()}"
        ),
        filing_url=(
            f"https://www.sec.gov/test/{rule.ticker.lower()}"
        ),
        published_at=_NOW,
        detected_at=_NOW,
        parser_name=f"test_{rule.ticker.lower()}",
        parser_version="1",
        confidence=Decimal("1"),
        document_fingerprint=f"fingerprint-{rule.ticker}",
    )


class EarningsHostedResolutionWorkerTests(unittest.TestCase):
    def test_checked_in_sources_run_real_strategy_in_shadow(self) -> None:
        rules = checked_in_shadow_rules()
        by_ticker = {rule.ticker: rule for rule in rules}
        profiles = tuple(_profile(rule) for rule in rules)
        facts = (
            _fact(by_ticker["AAPL"], "1.90"),
            _fact(by_ticker["AMZN"], "1.83"),
            _fact(by_ticker["ARCC"], "0.48"),
            _fact(by_ticker["BA"], "-0.31"),
            _fact(by_ticker["CBRE"], "1.33"),
            _fact(by_ticker["CI"], "7.61"),
            _fact(by_ticker["CSGP"], "0.11"),
            _fact(by_ticker["CZR"], "0.06"),
            _fact(by_ticker["DLB"], "0.68"),
            _fact(by_ticker["EA"], "0.81"),
            _fact(by_ticker["EBAY"], "1.52"),
            _fact(by_ticker["F"], "0.36"),
            _fact(by_ticker["GRMN"], "2.30"),
            _fact(by_ticker["HLT"], "2.26"),
            _fact(by_ticker["HOOD"], "0.44"),
            _fact(by_ticker["HUM"], "7.01"),
            _fact(by_ticker["IART"], "0.49"),
            _fact(by_ticker["ICE"], "1.85"),
            _fact(by_ticker["IVZ"], "0.67"),
            _fact(by_ticker["JBLU"], "-0.67"),
            _fact(by_ticker["KO"], "0.94"),
            _fact(by_ticker["MA"], "4.78"),
            _fact(by_ticker["META"], "7.21"),
            _fact(by_ticker["MSFT"], "4.22"),
            _fact(by_ticker["NVTS"], "-0.03"),
            _fact(by_ticker["NXPI"], "3.54"),
            _fact(by_ticker["PAG"], "3.40"),
            _fact(by_ticker["PG"], "1.42"),
            _fact(by_ticker["PYPL"], "1.29"),
            _fact(by_ticker["QCOM"], "2.24"),
            _fact(by_ticker["RCL"], "3.98"),
            _fact(by_ticker["RDDT"], "0.98"),
            _fact(by_ticker["RIVN"], "-0.77"),
            _fact(by_ticker["SBUX"], "0.70"),
            _fact(by_ticker["SOFI"], "0.12"),
            _fact(by_ticker["SPGI"], "4.96"),
            _fact(by_ticker["UPS"], "1.67"),
            _fact(by_ticker["V"], "3.23"),
            _fact(by_ticker["VIRT"], "1.83"),
            _fact(by_ticker["WAY"], "0.41"),
            _fact(by_ticker["WING"], "1.04"),
            _fact(by_ticker["WWD"], "2.42"),
            _fact(by_ticker["YUM"], "1.57"),
            _fact(by_ticker["BBBY"], "-0.25"),
        )
        earnings_store = _EarningsStore(facts)
        profile_store = _ProfileStore(profiles)
        worker = EarningsHostedResolutionWorker(
            settings=HostedResolutionSettings(
                mode=HostedResolutionMode.SHADOW,
                database_url="postgresql://unused",
            ),
            earnings_store=earnings_store,
            profile_store=profile_store,
            clock=lambda: _NOW,
        )

        preparations = worker.prepare()
        result = worker.poll_once()

        self.assertEqual(len(preparations), 44)
        self.assertTrue(all(item.ready for item in preparations))
        self.assertTrue(
            all(item.template_count == 2 for item in preparations)
        )
        self.assertEqual(worker.managed_count, 44)
        self.assertEqual(result.fact_count, 44)
        self.assertEqual(result.completed_count, 44)
        self.assertEqual(result.failed_count, 0)
        worker.close()

    def test_expired_profile_never_consumes_a_late_fact(self) -> None:
        rule = checked_in_shadow_rules()[0]
        worker = EarningsHostedResolutionWorker(
            settings=HostedResolutionSettings(
                mode=HostedResolutionMode.SHADOW,
                database_url="postgresql://unused",
            ),
            earnings_store=_EarningsStore(
                (_fact(rule, "-0.03"),)
            ),
            profile_store=_ProfileStore((_profile(rule),)),
            clock=lambda: _NOW + timedelta(hours=7),
        )

        worker.prepare()
        result = worker.poll_once()

        self.assertEqual(result.completed_count, 0)
        self.assertEqual(result.expired_count, 1)
        self.assertEqual(result.failed_count, 0)
        worker.close()

    def test_condition_mismatch_fails_before_polling(self) -> None:
        rule = checked_in_shadow_rules()[0]
        bad_profile = ResolutionExecutionProfile(
            **{
                **_profile(rule).__dict__,
                "condition_id": "0xwrong",
            }
        )
        worker = EarningsHostedResolutionWorker(
            settings=HostedResolutionSettings(
                mode=HostedResolutionMode.SHADOW,
                database_url="postgresql://unused",
            ),
            earnings_store=_EarningsStore(()),
            profile_store=_ProfileStore((bad_profile,)),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "condition_id",
        ):
            worker.prepare()

    def test_live_reprice_requires_supervision_before_executor(self) -> None:
        rule = checked_in_shadow_rules()[0]
        worker = EarningsHostedResolutionWorker(
            settings=HostedResolutionSettings(
                mode=HostedResolutionMode.LIVE,
                database_url="postgresql://unused",
                supervision_enabled=False,
            ),
            earnings_store=_EarningsStore(()),
            profile_store=_ProfileStore((_profile(rule),)),
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
        rule = checked_in_shadow_rules()[0]
        profiles = _ProfileStore(())
        worker = EarningsHostedResolutionWorker(
            settings=HostedResolutionSettings(
                mode=HostedResolutionMode.SHADOW,
                database_url="postgresql://unused",
            ),
            earnings_store=_EarningsStore(()),
            profile_store=profiles,
            clock=lambda: _NOW,
        )

        self.assertEqual(worker.reconcile_profiles(), ())
        profiles.set_profiles((_profile(rule),))
        attached = worker.reconcile_profiles()
        self.assertEqual(len(attached), 1)
        self.assertEqual(worker.managed_count, 1)
        self.assertEqual(worker.reconcile_profiles(), ())
        self.assertEqual(worker.managed_count, 1)

        profiles.set_profiles(())
        self.assertEqual(worker.reconcile_profiles(), ())
        self.assertEqual(worker.managed_count, 0)
        worker.close()

    def test_dynamic_preparation_failure_blocks_only_bad_profile(
        self,
    ) -> None:
        rule = checked_in_shadow_rules()[0]
        good = _profile(rule)
        bad = ResolutionExecutionProfile(
            **{
                **good.__dict__,
                "profile_key": f"{good.profile_key}-bad",
                "condition_id": "0xwrong",
            }
        )
        lifecycle = _LifecycleStore()
        worker = EarningsHostedResolutionWorker(
            settings=HostedResolutionSettings(
                mode=HostedResolutionMode.SHADOW,
                database_url="postgresql://unused",
            ),
            earnings_store=_EarningsStore(()),
            profile_store=_ProfileStore((good, bad)),
            lifecycle_store=lifecycle,
            clock=lambda: _NOW,
        )

        preparations = worker.reconcile_profiles()

        self.assertEqual(len(preparations), 2)
        self.assertEqual(worker.managed_count, 1)
        self.assertEqual(
            lifecycle.blocked,
            [
                (
                    bad.profile_key,
                    "live_profile_preparation_failed",
                )
            ],
        )
        worker.close()

    def test_completed_resolution_closes_lifecycle_exactly_once(
        self,
    ) -> None:
        rule = checked_in_shadow_rules()[0]
        lifecycle = _LifecycleStore()
        worker = EarningsHostedResolutionWorker(
            settings=HostedResolutionSettings(
                mode=HostedResolutionMode.SHADOW,
                database_url="postgresql://unused",
            ),
            earnings_store=_EarningsStore((_fact(rule, "-0.03"),)),
            profile_store=_ProfileStore((_profile(rule),)),
            lifecycle_store=lifecycle,
            clock=lambda: _NOW,
        )

        worker.prepare()
        first = worker.poll_once()
        second = worker.poll_once()

        self.assertEqual(first.completed_count, 1)
        self.assertEqual(second.completed_count, 1)
        self.assertEqual(
            lifecycle.completed,
            [
                (
                    _profile(rule).profile_key,
                    "resolution_execution_completed",
                )
            ],
        )
        worker.close()

    def test_completed_lifecycle_write_retries_without_reexecution(
        self,
    ) -> None:
        class FlakyLifecycle(_LifecycleStore):
            def __init__(self) -> None:
                super().__init__()
                self.attempts = 0

            def complete_active_profile(
                self,
                *,
                profile_key: str,
                reason_code: str,
            ) -> None:
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("temporary")
                super().complete_active_profile(
                    profile_key=profile_key,
                    reason_code=reason_code,
                )

        rule = checked_in_shadow_rules()[0]
        lifecycle = FlakyLifecycle()
        worker = EarningsHostedResolutionWorker(
            settings=HostedResolutionSettings(
                mode=HostedResolutionMode.SHADOW,
                database_url="postgresql://unused",
            ),
            earnings_store=_EarningsStore((_fact(rule, "-0.03"),)),
            profile_store=_ProfileStore((_profile(rule),)),
            lifecycle_store=lifecycle,
            clock=lambda: _NOW,
        )

        worker.prepare()
        worker.poll_once()
        worker.poll_once()
        worker.poll_once()

        self.assertEqual(lifecycle.attempts, 2)
        self.assertEqual(len(lifecycle.completed), 1)
        worker.close()


class HostedResolutionSettingsTests(unittest.TestCase):
    def test_defaults_to_non_submitting_shadow_mode(self) -> None:
        settings = HostedResolutionSettings.from_env(
            {
                "DATABASE_URL_SERVER_EXT": (
                    "postgresql://unused"
                ),
            }
        )

        self.assertEqual(
            settings.mode,
            HostedResolutionMode.SHADOW,
        )
        self.assertFalse(settings.supervision_enabled)
        self.assertEqual(
            settings.run_journal_reconcile_interval,
            2,
        )

    def test_configures_run_journal_reconcile_interval(self) -> None:
        settings = HostedResolutionSettings.from_env(
            {
                "DATABASE_URL_SERVER_EXT": (
                    "postgresql://unused"
                ),
                "RESOLUTION_RUN_JOURNAL_RECONCILE_SEC": "0.5",
            }
        )

        self.assertEqual(
            settings.run_journal_reconcile_interval,
            0.5,
        )

    def test_rejects_unknown_mode(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "shadow.*preflight.*live",
        ):
            HostedResolutionSettings.from_env(
                {
                    "DATABASE_URL_SERVER_EXT": (
                        "postgresql://unused"
                    ),
                    "RESOLUTION_ORCHESTRATOR_MODE": "armed",
                }
            )


if __name__ == "__main__":
    unittest.main()
