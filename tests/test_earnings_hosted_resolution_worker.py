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

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def load_enabled(self, *, source_name: str | None = None) -> tuple:
        assert source_name == EARNINGS_SOURCE_NAME
        return self._profiles


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
            _fact(by_ticker["BA"], "-0.31"),
            _fact(by_ticker["CSGP"], "0.11"),
            _fact(by_ticker["CZR"], "0.06"),
            _fact(by_ticker["NVTS"], "-0.03"),
            _fact(by_ticker["NXPI"], "3.54"),
            _fact(by_ticker["RCL"], "3.98"),
            _fact(by_ticker["WWD"], "2.42"),
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

        self.assertEqual(len(preparations), 8)
        self.assertTrue(all(item.ready for item in preparations))
        self.assertTrue(
            all(item.template_count == 2 for item in preparations)
        )
        self.assertEqual(worker.managed_count, 8)
        self.assertEqual(result.fact_count, 8)
        self.assertEqual(result.completed_count, 8)
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
