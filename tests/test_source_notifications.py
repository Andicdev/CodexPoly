from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.domain import ResolutionSignal, SignalEvidence
from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsMarketRule,
    EarningsMetric,
    EarningsProvider,
    EpsBasis,
    SourceAuthority,
)
from cbr_trading.mstr_btc import (
    MstrBtcFactCandidate,
    MstrBtcProvider,
    MstrBtcValueDerivation,
)
from cbr_trading.notifications import (
    ClaimedNotification,
    source_event_notification_from_earnings,
    source_event_notification_from_mstr,
)
from cbr_trading.notifications.hosted_worker import (
    NotificationHostedWorker,
)
from cbr_trading.notifications.settings import NotificationWorkerSettings


_NOW = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)


class _Outbox:
    def __init__(self, claim=None):
        self.claim = claim
        self.transitions = []

    def claim_next(self, *, lease_seconds):
        self.transitions.append(("claim", lease_seconds))
        claim, self.claim = self.claim, None
        return claim

    def mark_sent(self, row_id):
        self.transitions.append(("sent", row_id))

    def mark_failed(
        self,
        row_id,
        *,
        error_code,
        retry_delay_seconds,
    ):
        self.transitions.append(
            ("failed", row_id, error_code, retry_delay_seconds)
        )


class _Sender:
    def __init__(self, *, error=None):
        self.messages = []
        self.error = error

    def send_text(self, text):
        self.messages.append(text)
        if self.error is not None:
            raise self.error


def _settings() -> NotificationWorkerSettings:
    return NotificationWorkerSettings(
        database_url="postgresql://configured",
        telegram_bot_token="configured",
        telegram_chat_id="configured",
        lease_seconds=15,
        retry_delay=7,
    )


class SourceNotificationContractTests(unittest.TestCase):
    def test_earnings_event_has_one_stable_notification_key(self) -> None:
        candidate = EarningsDocumentCandidate(
            scope_id="earnings:NVTS:2026Q2",
            provider=EarningsProvider.SEC,
            provider_event_id="accession",
            ticker="NVTS",
            cik="1821769",
            form_type="8-K",
            items=("Item 2.02",),
            document_type="EX-99.1",
            source_url="https://www.sec.gov/nvts.htm",
            filing_url="https://www.sec.gov/nvts-index.htm",
            filed_at=_NOW,
            received_at=_NOW,
            authority=SourceAuthority.OFFICIAL_COMPANY,
            transport_fingerprint="fingerprint",
        )
        signal = ResolutionSignal(
            signal_id=candidate.scope_id,
            source="earnings_resolution",
            subject="company:NVTS:earnings:2026Q2",
            metric="company.earnings.eps.non_gaap",
            value=Decimal("0.07"),
            unit="USD",
            detected_at=_NOW,
            published_at=_NOW,
            evidence=(
                SignalEvidence(source_url=candidate.source_url),
            ),
            attributes={
                "ticker": "NVTS",
                "fiscal_year": 2026,
                "fiscal_quarter": 2,
                "provider": "sec",
            },
        )

        notification = source_event_notification_from_earnings(
            candidate=candidate,
            signal=signal,
            rule=EarningsMarketRule(
                rule_key="nvts-q2",
                scope_id=candidate.scope_id,
                ticker="NVTS",
                cik="1821769",
                fiscal_year=2026,
                fiscal_quarter=2,
                period_end=datetime(2026, 6, 30).date(),
                estimated_release_at=_NOW,
                metric=EarningsMetric.NON_GAAP_EPS,
                primary_basis=EpsBasis.DILUTED,
                fallback_basis=EpsBasis.BASIC_AND_DILUTED,
                comparison_op=">",
                strike=Decimal("0.04"),
            ),
        )

        self.assertEqual(
            notification.notification_key,
            "earnings:sec:accession:earnings:NVTS:2026Q2",
        )
        self.assertIn("Value: 0.07 USD", notification.message_text)
        self.assertIn("-> YES", notification.message_text)

    def test_mstr_event_is_one_message_for_all_market_rules(self) -> None:
        fact = MstrBtcFactCandidate(
            scope_id="mstr-btc:2026-07-21:2026-07-27",
            provider=MstrBtcProvider.STRATEGY_LEDGER,
            provider_event_id="ledger-row",
            baseline_state_id="17",
            holdings_before_btc=843_775,
            holdings_after_btc=845_275,
            net_change_btc=1_500,
            acquired_btc=1_500,
            sold_btc=0,
            acquired_derivation=MstrBtcValueDerivation.EXPLICIT,
            sold_derivation=MstrBtcValueDerivation.HOLDINGS_DELTA,
            holdings_crosscheck_difference_btc=0,
            source_url="https://www.strategy.com/ledger",
            filing_url="https://www.sec.gov/mstr.pdf",
            published_at=_NOW,
            detected_at=_NOW,
            parser_name="ledger",
            parser_version="1",
            document_fingerprint="fingerprint",
            attributes={"ticker": "MSTR", "cik": "1050446"},
        )

        notification = source_event_notification_from_mstr(
            fact=fact,
            signals=(
                ResolutionSignal(
                    signal_id=f"{fact.scope_id}:purchase-any",
                    source="mstr_btc_resolution",
                    subject="company:MSTR:bitcoin",
                    metric="company.mstr.bitcoin.acquired",
                    value=Decimal("1500"),
                    unit="BTC",
                    detected_at=_NOW,
                    attributes={
                        "activity": "acquired",
                        "comparison_op": ">",
                        "threshold_btc": "0",
                    },
                ),
                ResolutionSignal(
                    signal_id=f"{fact.scope_id}:purchase-1000",
                    source="mstr_btc_resolution",
                    subject="company:MSTR:bitcoin",
                    metric="company.mstr.bitcoin.acquired",
                    value=Decimal("1500"),
                    unit="BTC",
                    detected_at=_NOW,
                    attributes={
                        "activity": "acquired",
                        "comparison_op": ">",
                        "threshold_btc": "1000",
                    },
                ),
                ResolutionSignal(
                    signal_id=f"{fact.scope_id}:sold-any",
                    source="mstr_btc_resolution",
                    subject="company:MSTR:bitcoin",
                    metric="company.mstr.bitcoin.sold",
                    value=Decimal("0"),
                    unit="BTC",
                    detected_at=_NOW,
                    attributes={
                        "activity": "sold",
                        "comparison_op": ">",
                        "threshold_btc": "0",
                    },
                ),
            ),
        )

        self.assertIn(
            "Market rules evaluated: 3",
            notification.message_text,
        )
        self.assertEqual(notification.event_kind, "mstr_btc")

    def test_settings_hide_telegram_credentials(self) -> None:
        settings = NotificationWorkerSettings.from_env(
            {
                "CBR_DATABASE_URL": "postgresql://user:secret@db/app",
                "TG_BOT_TOKEN": "telegram-secret",
                "TELEGRAM_INGEST_CHAT_ID": "private-chat",
            }
        )

        rendered = repr(settings)
        self.assertNotIn("telegram-secret", rendered)
        self.assertNotIn("private-chat", rendered)


class NotificationHostedWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_message_is_marked_sent_only_after_sender_returns(
        self,
    ) -> None:
        store = _Outbox(
            ClaimedNotification(
                row_id=41,
                notification_key="event",
                message_text="confirmed",
                attempt_count=1,
            )
        )
        sender = _Sender()
        worker = NotificationHostedWorker(
            settings=_settings(),
            store=store,
            sender=sender,
        )

        processed = await worker.run_once()

        self.assertTrue(processed)
        self.assertEqual(sender.messages, ["confirmed"])
        self.assertEqual(
            store.transitions,
            [("claim", 15), ("sent", 41)],
        )

    async def test_sender_failure_is_retried_without_secret_text(self) -> None:
        store = _Outbox(
            ClaimedNotification(
                row_id=42,
                notification_key="event",
                message_text="confirmed",
                attempt_count=1,
            )
        )
        worker = NotificationHostedWorker(
            settings=_settings(),
            store=store,
            sender=_Sender(error=RuntimeError("do not persist this")),
        )

        processed = await worker.run_once()

        self.assertTrue(processed)
        self.assertEqual(
            store.transitions[-1],
            ("failed", 42, "RuntimeError", 7),
        )


if __name__ == "__main__":
    unittest.main()
