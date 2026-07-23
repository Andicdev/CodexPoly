from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable


_CONDITION_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class MarketPreflightError(RuntimeError):
    """Safe failure while resolving current public market state."""


@dataclass(frozen=True)
class MarketSnapshot:
    condition_id: str
    question: str
    outcome: str
    token_id: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    last_trade_price: Decimal | None
    tick_size: Decimal
    minimum_order_size: Decimal
    neg_risk: bool

    def would_cross_buy(self, price: Decimal) -> bool:
        return self.best_ask is not None and price >= self.best_ask


class PolymarketMarketGateway:
    """Resolve a condition and its order book with the official SDK."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any] | None = None,
    ):
        self._client_factory = client_factory

    def load_snapshot(
        self,
        *,
        condition_id: str,
        outcome: str,
    ) -> MarketSnapshot:
        normalized_condition = str(condition_id or "").strip().lower()
        if not _CONDITION_ID_RE.fullmatch(normalized_condition):
            raise MarketPreflightError("Invalid Polymarket condition_id")

        normalized_outcome = str(outcome or "").strip().upper()
        if normalized_outcome not in {"YES", "NO"}:
            raise MarketPreflightError(
                "Polymarket outcome must be YES or NO"
            )

        client = self._new_client()
        try:
            page = client.list_markets(
                condition_ids=[normalized_condition],
                page_size=2,
            ).first_page()
            markets = tuple(page.items)
            if len(markets) != 1:
                raise MarketPreflightError(
                    "Expected exactly one market for condition_id; "
                    f"found {len(markets)}"
                )
            market = markets[0]
            self._validate_market(market, normalized_condition)

            market_outcome = getattr(
                market.outcomes,
                normalized_outcome.lower(),
                None,
            )
            token_id = str(
                getattr(market_outcome, "token_id", None) or ""
            ).strip()
            if not token_id:
                raise MarketPreflightError(
                    f"Market has no {normalized_outcome} token_id"
                )

            book = client.get_order_book(token_id=token_id)
            book_condition = str(
                getattr(book, "condition_id", "") or ""
            ).strip().lower()
            if book_condition != normalized_condition:
                raise MarketPreflightError(
                    "Order book condition_id does not match the rule"
                )

            tick_size = Decimal(str(book.tick_size))
            minimum_order_size = Decimal(str(book.min_order_size))
            if tick_size <= 0 or minimum_order_size <= 0:
                raise MarketPreflightError(
                    "Order book returned invalid trading constraints"
                )

            return MarketSnapshot(
                condition_id=normalized_condition,
                question=str(market.question or "").strip(),
                outcome=normalized_outcome,
                token_id=token_id,
                best_bid=_best_bid(book.bids),
                best_ask=_best_ask(book.asks),
                last_trade_price=_optional_decimal(
                    book.last_trade_price
                ),
                tick_size=tick_size,
                minimum_order_size=minimum_order_size,
                neg_risk=bool(book.neg_risk),
            )
        except MarketPreflightError:
            raise
        except Exception as exc:
            raise MarketPreflightError(
                "Polymarket public preflight failed: "
                f"{type(exc).__name__}"
            ) from exc
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _new_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        try:
            from polymarket import PublicClient
        except ImportError as exc:
            raise MarketPreflightError(
                "Live preflight requires polymarket-client"
            ) from exc
        return PublicClient()

    @staticmethod
    def _validate_market(market: Any, condition_id: str) -> None:
        actual_condition = str(
            getattr(market, "condition_id", "") or ""
        ).strip().lower()
        if actual_condition != condition_id:
            raise MarketPreflightError(
                "Gamma market condition_id does not match the rule"
            )

        state = market.state
        if (
            state.active is not True
            or state.closed is True
            or state.archived is True
            or state.accepting_orders is not True
            or state.enable_order_book is not True
        ):
            raise MarketPreflightError(
                "Market is not active and accepting order-book orders"
            )


def _best_bid(levels: Any) -> Decimal | None:
    prices = [Decimal(str(level.price)) for level in levels]
    return max(prices) if prices else None


def _best_ask(levels: Any) -> Decimal | None:
    prices = [Decimal(str(level.price)) for level in levels]
    return min(prices) if prices else None


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
