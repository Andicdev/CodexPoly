from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from neg_risk_trading.catalog import (
    CatalogPage,
    parse_catalog_page,
)
from neg_risk_trading.catalog_service import (
    ContinuousCatalogScanner,
)
from neg_risk_trading.catalog_repository import (
    SqlAlchemyCatalogRepository,
)
from neg_risk_trading.domain import NegRiskContractError
from neg_risk_trading.polymarket import (
    GAMMA_BASE_URL,
    PolymarketPublicClient,
    PublicApiError,
)
from neg_risk_trading.settings import NegRiskCatalogSettings


def _condition(index: int) -> str:
    return "0x" + format((index % 15) + 1, "x") * 64


def _event(index: int = 1) -> dict:
    return {
        "id": f"event-{index}",
        "slug": f"event-{index}",
        "title": f"Event {index}",
        "active": True,
        "closed": False,
        "archived": False,
        "negRisk": True,
        "negRiskAugmented": False,
        "enableOrderBook": True,
        "updatedAt": "2026-07-30T12:00:00Z",
        "endDate": "2026-09-30T12:00:00Z",
        "volume": "5000",
        "volume24hr": "250",
        "volume1wk": "1000",
        "volume1mo": "3000",
        "volume1yr": "5000",
        "liquidityClob": "750",
        "openInterest": "900",
    }


def _market(index: int = 1, *, event_index: int = 1) -> dict:
    return {
        "id": f"market-{index}",
        "conditionId": _condition(index),
        "slug": f"market-{index}",
        "question": f"Outcome {index}?",
        "active": True,
        "closed": False,
        "archived": False,
        "negRisk": True,
        "negRiskOther": False,
        "acceptingOrders": True,
        "enableOrderBook": True,
        "events": [_event(event_index)],
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.009", "0.991"]),
        "clobTokenIds": json.dumps(
            [str(10_000 + index), str(20_000 + index)]
        ),
        "volume": "1000",
        "volume24hr": "50",
        "volume1wk": "300",
        "volume1mo": "900",
        "volume1yr": "1000",
        "liquidityClob": "125",
        "bestBid": "0.008",
        "bestAsk": "0.010",
        "spread": "0.002",
        "orderPriceMinTickSize": "0.001",
        "orderMinSize": "5",
        "feesEnabled": True,
        "feeType": "politics_fees",
        "feeSchedule": {
            "rate": "0.04",
            "exponent": 1,
            "takerOnly": True,
            "rebateRate": "0.25",
        },
        "rewardsMinSize": "50",
        "rewardsMaxSpread": "4.5",
        "holdingRewardsEnabled": False,
        "updatedAt": "2026-07-30T12:00:00Z",
        "endDate": "2026-09-30T12:00:00Z",
    }


def _page(
    markets: list[dict],
    *,
    cursor: str | None,
) -> CatalogPage:
    return parse_catalog_page(
        {
            "markets": markets,
            "next_cursor": cursor,
        }
    )


class CatalogParserTests(unittest.TestCase):
    def test_parses_active_neg_risk_market_metadata(self) -> None:
        page = _page([_market()], cursor="next")

        self.assertEqual(page.gamma_market_count, 1)
        self.assertEqual(page.neg_risk_market_count, 1)
        self.assertEqual(len(page.events), 1)
        self.assertEqual(len(page.markets), 1)
        market = page.markets[0]
        self.assertEqual(market.fee_category, "politics")
        self.assertEqual(market.fee_rate, Decimal("0.04"))
        self.assertEqual(market.tick_size, Decimal("0.001"))
        self.assertEqual(market.yes_price, Decimal("0.009"))
        self.assertTrue(market.metadata_complete)
        self.assertEqual(page.issue_count, 0)

    def test_skips_non_neg_risk_market(self) -> None:
        market = _market()
        market["negRisk"] = False

        page = _page([market], cursor=None)

        self.assertEqual(page.gamma_market_count, 1)
        self.assertEqual(page.neg_risk_market_count, 0)
        self.assertFalse(page.markets)

    def test_preserves_market_with_incomplete_fee_metadata(
        self,
    ) -> None:
        market = _market()
        del market["feeSchedule"]

        page = _page([market], cursor=None)

        self.assertEqual(len(page.markets), 1)
        self.assertFalse(page.markets[0].metadata_complete)
        self.assertIn(
            "fee_schedule_incomplete",
            page.markets[0].issue_codes,
        )
        self.assertGreater(page.issue_count, 0)

    def test_rejects_invalid_page_contract(self) -> None:
        with self.assertRaisesRegex(
            NegRiskContractError,
            "catalog_markets_missing",
        ):
            parse_catalog_page({"next_cursor": None})

    def test_unlinked_neg_risk_market_is_counted_as_skipped(
        self,
    ) -> None:
        market = _market()
        market["events"] = []

        page = _page([market], cursor=None)

        self.assertEqual(page.neg_risk_market_count, 1)
        self.assertEqual(page.skipped_market_count, 1)
        self.assertFalse(page.markets)

    def test_market_linked_to_inactive_event_is_preserved(
        self,
    ) -> None:
        market = _market()
        market["events"][0]["active"] = False

        page = _page([market], cursor=None)

        self.assertEqual(page.skipped_market_count, 0)
        self.assertEqual(len(page.markets), 1)
        self.assertFalse(page.events[0].active)


class _Response:
    def __init__(self, payload: object):
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, payload: object):
        self.payload = payload
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: object) -> _Response:
        self.calls.append(url)
        return _Response(self.payload)


class CatalogClientTests(unittest.TestCase):
    def test_uses_stable_keyset_endpoint_and_encoded_cursor(
        self,
    ) -> None:
        session = _Session(
            {
                "markets": [_market()],
                "next_cursor": None,
            }
        )
        client = PolymarketPublicClient(session=session)

        page = client.fetch_catalog_page(
            after_cursor="opaque+/=",
            page_size=100,
        )

        self.assertEqual(len(page.markets), 1)
        self.assertTrue(
            session.calls[0].startswith(
                f"{GAMMA_BASE_URL}/markets/keyset?"
            )
        )
        self.assertIn("closed=false", session.calls[0])
        self.assertIn("after_cursor=opaque%2B%2F%3D", session.calls[0])
        self.assertNotIn("offset=", session.calls[0])


class _Repository:
    def __init__(self):
        self.scan_id = UUID("00000000-0000-0000-0000-000000000001")
        self.pages: list[CatalogPage] = []
        self.completed = False
        self.failed_reason: str | None = None

    def ensure_ready(self) -> None:
        return None

    def start_scan(self, **kwargs: object) -> UUID:
        return self.scan_id

    def record_page(
        self,
        *,
        scan_id: UUID,
        page: CatalogPage,
        observed_at: datetime,
    ) -> None:
        self.pages.append(page)

    def complete_scan(self, **kwargs: object) -> None:
        self.completed = True

    def fail_scan(
        self,
        *,
        reason_code: str,
        **kwargs: object,
    ) -> None:
        self.failed_reason = reason_code

    def close(self) -> None:
        return None


class _Client:
    def __init__(self, pages: list[CatalogPage]):
        self.pages = list(pages)
        self.cursors: list[str | None] = []

    def fetch_catalog_page(
        self,
        *,
        after_cursor: str | None,
        page_size: int,
    ) -> CatalogPage:
        self.cursors.append(after_cursor)
        return self.pages.pop(0)


def _settings(**changes: object) -> NegRiskCatalogSettings:
    values = {
        "database_url": "postgresql://configured",
        "maximum_pages": 10,
        "maximum_markets": 1000,
    }
    values.update(changes)
    return NegRiskCatalogSettings(**values)


class CatalogServiceTests(unittest.TestCase):
    def test_completes_exhaustive_two_page_scan(self) -> None:
        repository = _Repository()
        client = _Client(
            [
                _page([_market(1)], cursor="cursor-2"),
                _page(
                    [_market(2, event_index=2)],
                    cursor=None,
                ),
            ]
        )
        scanner = ContinuousCatalogScanner(
            settings=_settings(),
            repository=repository,  # type: ignore[arg-type]
            public_client=client,  # type: ignore[arg-type]
        )

        result = scanner.run_once()

        self.assertTrue(repository.completed)
        self.assertIsNone(repository.failed_reason)
        self.assertEqual(len(repository.pages), 2)
        self.assertEqual(client.cursors, [None, "cursor-2"])
        self.assertEqual(result.gamma_market_count, 2)
        self.assertEqual(result.neg_risk_market_count, 2)
        self.assertEqual(result.event_count, 2)

    def test_repeated_cursor_fails_without_completing_scan(
        self,
    ) -> None:
        repository = _Repository()
        client = _Client(
            [
                _page([_market(1)], cursor="same"),
                _page([_market(2)], cursor="same"),
            ]
        )
        scanner = ContinuousCatalogScanner(
            settings=_settings(),
            repository=repository,  # type: ignore[arg-type]
            public_client=client,  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(
            PublicApiError,
            "gamma_catalog_cursor_repeated",
        ):
            scanner.run_once()

        self.assertFalse(repository.completed)
        self.assertEqual(
            repository.failed_reason,
            "gamma_catalog_cursor_repeated",
        )


class _SqlSession:
    def __init__(self):
        self.statements: list[tuple[str, object]] = []
        self.commits = 0

    def __enter__(self) -> _SqlSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        statement: str,
        params: object = None,
    ) -> None:
        self.statements.append((statement, params))

    def commit(self) -> None:
        self.commits += 1


class CatalogRepositoryTests(unittest.TestCase):
    def test_pages_stage_before_atomic_promotion(self) -> None:
        session = _SqlSession()
        repository = SqlAlchemyCatalogRepository(
            session_factory=lambda: session,
            text_factory=lambda value: value,
        )
        scan_id = UUID(
            "00000000-0000-0000-0000-000000000001"
        )
        page = _page([_market()], cursor=None)
        observed_at = datetime.now(timezone.utc)

        repository.record_page(
            scan_id=scan_id,
            page=page,
            observed_at=observed_at,
        )

        staged_sql = "\n".join(
            statement
            for statement, _params in session.statements
        )
        self.assertIn(
            "INSERT INTO neg_risk_catalog_scan_events",
            staged_sql,
        )
        self.assertIn(
            "INSERT INTO neg_risk_catalog_scan_markets",
            staged_sql,
        )
        self.assertNotIn(
            "INSERT INTO neg_risk_catalog_events_current",
            staged_sql,
        )

        session.statements.clear()
        repository.complete_scan(
            scan_id=scan_id,
            completed_at=observed_at,
            duration_ms=100,
        )

        promoted_sql = "\n".join(
            statement
            for statement, _params in session.statements
        )
        self.assertIn(
            "INSERT INTO neg_risk_catalog_events_current",
            promoted_sql,
        )
        self.assertIn(
            "INSERT INTO neg_risk_catalog_markets_current",
            promoted_sql,
        )
        self.assertIn(
            "status = 'COMPLETE'",
            promoted_sql,
        )


class CatalogSettingsTests(unittest.TestCase):
    def test_environment_is_shadow_only(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "must remain 'shadow'",
        ):
            _settings(mode="live").validate()

    def test_default_scan_cadence_is_bounded(self) -> None:
        settings = _settings()

        settings.validate()
        self.assertEqual(settings.poll_interval_seconds, 900)
        self.assertEqual(settings.page_size, 100)


if __name__ == "__main__":
    unittest.main()
