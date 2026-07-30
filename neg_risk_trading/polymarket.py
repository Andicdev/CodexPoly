from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from neg_risk_trading.domain import (
    BookLevel,
    FeeSchedule,
    MarketSnapshot,
    NegRiskContractError,
    NegRiskEvent,
    OrderBook,
    OutcomeMarket,
    RewardConfig,
)


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"
DEFAULT_FED_SEPTEMBER_SLUG = "fed-decision-in-september-762"

_CONDITION_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class PublicApiError(RuntimeError):
    """A classified public-market-data failure with no response details."""

    def __init__(self, reason_code: str):
        normalized = str(reason_code or "").strip()
        if not normalized:
            raise ValueError("reason_code is required")
        super().__init__(normalized)
        self.reason_code = normalized


class _PublicTransportFailure(OSError):
    pass


class _UrllibResponse:
    def __init__(self, *, status: int, content: bytes):
        self.status = int(status)
        self.content = content

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise _PublicTransportFailure("http_status_failed")


def _encoded_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class _UrllibSession:
    def __init__(self, *, maximum_response_bytes: int):
        self.headers: dict[str, str] = {}
        self._maximum_response_bytes = maximum_response_bytes

    def _request(
        self,
        url: str,
        *,
        method: str,
        body: bytes | None,
        timeout: object,
    ) -> _UrllibResponse:
        if isinstance(timeout, tuple):
            timeout_seconds = max(float(value) for value in timeout)
        else:
            timeout_seconds = float(timeout)
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(
                request,
                timeout=timeout_seconds,
            ) as response:
                content = response.read(
                    self._maximum_response_bytes + 1
                )
                status = int(
                    getattr(response, "status", 200)
                )
        except (OSError, TimeoutError, URLError) as exc:
            raise _PublicTransportFailure(
                "public_request_failed"
            ) from exc
        return _UrllibResponse(
            status=status,
            content=content,
        )

    def get(self, url: str, *, timeout: object) -> _UrllibResponse:
        return self._request(
            url,
            method="GET",
            body=None,
            timeout=timeout,
        )

    def post(
        self,
        url: str,
        *,
        json: object,
        timeout: object,
    ) -> _UrllibResponse:
        return self._request(
            url,
            method="POST",
            body=_encoded_json(json),
            timeout=timeout,
        )


def extract_event_slug(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise NegRiskContractError("event_slug_required")
    if "://" not in raw:
        slug = raw.strip("/")
    else:
        parsed = urlparse(raw)
        if (parsed.hostname or "").lower() not in {
            "polymarket.com",
            "www.polymarket.com",
        }:
            raise NegRiskContractError("event_host_invalid")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2 or parts[0].lower() != "event":
            raise NegRiskContractError("event_url_invalid")
        slug = parts[1].lower()
    if not _SLUG_RE.fullmatch(slug):
        raise NegRiskContractError("event_slug_invalid")
    return slug


def _mapping(value: object, *, reason_code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NegRiskContractError(reason_code)
    return value


def _list(value: object, *, reason_code: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise NegRiskContractError(reason_code) from exc
        if isinstance(parsed, list):
            return parsed
    raise NegRiskContractError(reason_code)


def _decimal_field(
    value: object,
    *,
    reason_code: str,
) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise NegRiskContractError(reason_code) from exc
    if not result.is_finite():
        raise NegRiskContractError(reason_code)
    return result


def _integer_field(
    value: object,
    *,
    reason_code: str,
) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise NegRiskContractError(reason_code) from exc


def _active_market(raw_market: Mapping[str, Any]) -> bool:
    return (
        raw_market.get("active") is True
        and raw_market.get("closed") is not True
        and raw_market.get("archived") is not True
    )


def _parse_fee_schedule(
    raw_market: Mapping[str, Any],
) -> FeeSchedule:
    enabled = raw_market.get("feesEnabled")
    raw_schedule = raw_market.get("feeSchedule")
    if enabled is False and raw_schedule in (None, {}):
        return FeeSchedule(
            rate=Decimal("0"),
            exponent=1,
            taker_only=True,
            rebate_rate=Decimal("0"),
        )
    if enabled is not True:
        raise NegRiskContractError("fees_enabled_ambiguous")
    schedule = _mapping(
        raw_schedule,
        reason_code="fee_schedule_missing",
    )
    if "rate" not in schedule or "exponent" not in schedule:
        raise NegRiskContractError("fee_schedule_incomplete")
    return FeeSchedule(
        rate=_decimal_field(
            schedule["rate"],
            reason_code="fee_rate_invalid",
        ),
        exponent=_integer_field(
            schedule["exponent"],
            reason_code="fee_exponent_invalid",
        ),
        taker_only=schedule.get("takerOnly") is True,
        rebate_rate=_decimal_field(
            schedule.get("rebateRate", "0"),
            reason_code="rebate_rate_invalid",
        ),
    )


def _parse_date(value: object, *, reason_code: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise NegRiskContractError(reason_code) from exc


def _active_reward_daily_rate(
    raw_market: Mapping[str, Any],
    *,
    as_of: date,
) -> Decimal:
    raw_rewards = raw_market.get("clobRewards")
    if raw_rewards in (None, []):
        return Decimal("0")
    rewards = _list(
        raw_rewards,
        reason_code="clob_rewards_invalid",
    )
    total = Decimal("0")
    for raw_reward in rewards:
        reward = _mapping(
            raw_reward,
            reason_code="clob_reward_invalid",
        )
        if "rewardsDailyRate" not in reward:
            raise NegRiskContractError(
                "clob_reward_daily_rate_missing"
            )
        start = _parse_date(
            reward.get("startDate"),
            reason_code="clob_reward_start_date_invalid",
        )
        end = _parse_date(
            reward.get("endDate"),
            reason_code="clob_reward_end_date_invalid",
        )
        if start <= as_of <= end:
            total += _decimal_field(
                reward["rewardsDailyRate"],
                reason_code="clob_reward_daily_rate_invalid",
            )
    return total


def parse_gamma_event(
    payload: Mapping[str, Any],
    *,
    expected_slug: str,
    as_of: date,
) -> NegRiskEvent:
    event = _mapping(
        payload,
        reason_code="gamma_event_invalid",
    )
    actual_slug = str(event.get("slug") or "").strip()
    if actual_slug != expected_slug:
        raise NegRiskContractError("gamma_event_slug_mismatch")
    if (
        event.get("active") is not True
        or event.get("closed") is True
        or event.get("archived") is True
    ):
        raise NegRiskContractError("gamma_event_not_active")
    if event.get("negRisk") is not True:
        raise NegRiskContractError("gamma_event_not_neg_risk")
    if not isinstance(event.get("negRiskAugmented"), bool):
        raise NegRiskContractError(
            "gamma_neg_risk_augmented_ambiguous"
        )
    raw_markets = _list(
        event.get("markets"),
        reason_code="gamma_markets_missing",
    )
    markets: list[OutcomeMarket] = []
    for raw_market_value in raw_markets:
        raw_market = _mapping(
            raw_market_value,
            reason_code="gamma_market_invalid",
        )
        if not _active_market(raw_market):
            raise NegRiskContractError("gamma_market_not_active")
        condition_id = str(
            raw_market.get("conditionId")
            or raw_market.get("condition_id")
            or ""
        ).strip().lower()
        if not _CONDITION_ID_RE.fullmatch(condition_id):
            raise NegRiskContractError("condition_id_invalid")
        outcomes = [
            str(value).strip()
            for value in _list(
                raw_market.get("outcomes"),
                reason_code="market_outcomes_invalid",
            )
        ]
        token_ids = [
            str(value).strip()
            for value in _list(
                raw_market.get("clobTokenIds")
                or raw_market.get("clob_token_ids"),
                reason_code="market_token_ids_invalid",
            )
        ]
        if len(outcomes) != 2 or len(token_ids) != 2:
            raise NegRiskContractError("binary_market_invalid")
        normalized_outcomes = [
            outcome.lower()
            for outcome in outcomes
        ]
        if sorted(normalized_outcomes) != ["no", "yes"]:
            raise NegRiskContractError("binary_outcomes_invalid")
        yes_index = normalized_outcomes.index("yes")
        if "rewardsMinSize" not in raw_market:
            raise NegRiskContractError("reward_minimum_size_missing")
        if "rewardsMaxSpread" not in raw_market:
            raise NegRiskContractError(
                "reward_maximum_spread_missing"
            )
        markets.append(
            OutcomeMarket(
                market_id=str(raw_market.get("id") or "").strip(),
                condition_id=condition_id,
                slug=str(raw_market.get("slug") or "").strip(),
                question=str(
                    raw_market.get("question") or ""
                ).strip(),
                yes_token_id=token_ids[yes_index],
                no_token_id=token_ids[1 - yes_index],
                fee_schedule=_parse_fee_schedule(raw_market),
                rewards=RewardConfig(
                    minimum_size=_decimal_field(
                        raw_market["rewardsMinSize"],
                        reason_code="reward_minimum_size_invalid",
                    ),
                    maximum_spread_cents=_decimal_field(
                        raw_market["rewardsMaxSpread"],
                        reason_code="reward_maximum_spread_invalid",
                    ),
                    daily_rate=_active_reward_daily_rate(
                        raw_market,
                        as_of=as_of,
                    ),
                ),
            )
        )
    if not markets:
        raise NegRiskContractError("gamma_active_markets_missing")
    return NegRiskEvent(
        event_id=str(event.get("id") or "").strip(),
        slug=actual_slug,
        title=str(event.get("title") or "").strip(),
        neg_risk=True,
        augmented=event["negRiskAugmented"],
        markets=tuple(markets),
    )


def _parse_book_timestamp(value: object) -> int:
    raw = str(value or "").strip()
    if not raw.isdigit():
        raise NegRiskContractError("book_timestamp_invalid")
    timestamp = int(raw)
    if timestamp < 1_000_000_000_000:
        raise NegRiskContractError(
            "book_timestamp_not_milliseconds"
        )
    return timestamp


def _parse_levels(
    value: object,
    *,
    reason_code: str,
) -> tuple[BookLevel, ...]:
    raw_levels = _list(value, reason_code=reason_code)
    levels: list[BookLevel] = []
    for raw_level_value in raw_levels:
        raw_level = _mapping(
            raw_level_value,
            reason_code=reason_code,
        )
        if "price" not in raw_level or "size" not in raw_level:
            raise NegRiskContractError(reason_code)
        levels.append(
            BookLevel(
                price=_decimal_field(
                    raw_level["price"],
                    reason_code=f"{reason_code}_price_invalid",
                ),
                size=_decimal_field(
                    raw_level["size"],
                    reason_code=f"{reason_code}_size_invalid",
                ),
            )
        )
    return tuple(levels)


def parse_clob_books(
    payload: Sequence[Mapping[str, Any]],
    *,
    event: NegRiskEvent,
) -> dict[str, OrderBook]:
    expected_asset_ids = {
        market.yes_token_id
        for market in event.markets
    }
    asset_books = _parse_clob_asset_books(
        payload,
        event=event,
        expected_asset_ids=expected_asset_ids,
    )
    return {
        book.condition_id: book
        for book in asset_books.values()
    }


def parse_clob_asset_books(
    payload: Sequence[Mapping[str, Any]],
    *,
    event: NegRiskEvent,
) -> dict[str, OrderBook]:
    """Parse one exact public book for every YES and NO asset."""
    return _parse_clob_asset_books(
        payload,
        event=event,
        expected_asset_ids=set(event.asset_ids),
    )


def _parse_clob_asset_books(
    payload: Sequence[Mapping[str, Any]],
    *,
    event: NegRiskEvent,
    expected_asset_ids: set[str],
) -> dict[str, OrderBook]:
    if not isinstance(payload, list):
        raise NegRiskContractError("clob_books_response_invalid")
    markets_by_token = {
        token_id: market
        for market in event.markets
        for token_id in (
            market.yes_token_id,
            market.no_token_id,
        )
    }
    books: dict[str, OrderBook] = {}
    seen_tokens: set[str] = set()
    for raw_book_value in payload:
        raw_book = _mapping(
            raw_book_value,
            reason_code="clob_book_invalid",
        )
        asset_id = str(raw_book.get("asset_id") or "").strip()
        if asset_id in seen_tokens:
            raise NegRiskContractError("clob_book_duplicate")
        seen_tokens.add(asset_id)
        market = markets_by_token.get(asset_id)
        if (
            market is None
            or asset_id not in expected_asset_ids
        ):
            raise NegRiskContractError("clob_book_asset_unexpected")
        condition_id = str(
            raw_book.get("market") or ""
        ).strip().lower()
        if condition_id != market.condition_id:
            raise NegRiskContractError(
                "clob_book_condition_mismatch"
            )
        if raw_book.get("neg_risk") is not True:
            raise NegRiskContractError("clob_book_not_neg_risk")
        books[asset_id] = OrderBook(
            condition_id=condition_id,
            asset_id=asset_id,
            timestamp_ms=_parse_book_timestamp(
                raw_book.get("timestamp")
            ),
            book_hash=str(raw_book.get("hash") or "").strip(),
            bids=_parse_levels(
                raw_book.get("bids"),
                reason_code="clob_bids_invalid",
            ),
            asks=_parse_levels(
                raw_book.get("asks"),
                reason_code="clob_asks_invalid",
            ),
            minimum_order_size=_decimal_field(
                raw_book.get("min_order_size"),
                reason_code="minimum_order_size_invalid",
            ),
            tick_size=_decimal_field(
                raw_book.get("tick_size"),
                reason_code="tick_size_invalid",
            ),
            neg_risk=True,
        )
    if seen_tokens != expected_asset_ids:
        raise NegRiskContractError("clob_book_set_incomplete")
    return books


@dataclass(frozen=True)
class MarketStreamBootstrap:
    event: NegRiskEvent
    books: Mapping[str, OrderBook]
    requested_at_ms: int
    received_at_ms: int
    gamma_duration_ms: int
    books_duration_ms: int

    def __post_init__(self) -> None:
        if set(self.books) != set(self.event.asset_ids):
            raise NegRiskContractError(
                "stream_bootstrap_book_set_mismatch"
            )
        object.__setattr__(
            self,
            "books",
            MappingProxyType(dict(self.books)),
        )


class PolymarketPublicClient:
    """Bounded, unauthenticated Gamma + CLOB snapshot client."""

    def __init__(
        self,
        *,
        connect_timeout: float = 2.0,
        read_timeout: float = 5.0,
        maximum_response_bytes: int = 8 * 1024 * 1024,
        session: Any | None = None,
    ):
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("public API timeouts must be positive")
        if maximum_response_bytes <= 0:
            raise ValueError(
                "maximum_response_bytes must be positive"
            )
        self._request_exception_types = (
            _PublicTransportFailure,
            OSError,
            TimeoutError,
        )
        self._session = (
            session
            if session is not None
            else _UrllibSession(
                maximum_response_bytes=maximum_response_bytes
            )
        )
        self._session.headers.update(
            {
                "User-Agent": "codexpoly-neg-risk-shadow/0.1",
                "Accept": "application/json",
            }
        )
        self._timeout = (
            float(connect_timeout),
            float(read_timeout),
        )
        self._maximum_response_bytes = int(
            maximum_response_bytes
        )

    def _response_json(
        self,
        response: Any,
        *,
        reason_prefix: str,
    ) -> Any:
        try:
            response.raise_for_status()
        except self._request_exception_types as exc:
            raise PublicApiError(
                f"{reason_prefix}_http_failed"
            ) from exc
        body = response.content
        if len(body) > self._maximum_response_bytes:
            raise PublicApiError(
                f"{reason_prefix}_body_too_large"
            )
        try:
            return json.loads(body)
        except (TypeError, UnicodeDecodeError, ValueError) as exc:
            raise PublicApiError(
                f"{reason_prefix}_json_invalid"
            ) from exc

    def fetch_snapshot(self, event_value: str) -> MarketSnapshot:
        slug = extract_event_slug(event_value)
        requested_at_ms = time.time_ns() // 1_000_000
        gamma_started = time.perf_counter_ns()
        try:
            gamma_response = self._session.get(
                f"{GAMMA_BASE_URL}/events/slug/{slug}",
                timeout=self._timeout,
            )
        except self._request_exception_types as exc:
            raise PublicApiError("gamma_request_failed") from exc
        gamma_payload = self._response_json(
            gamma_response,
            reason_prefix="gamma",
        )
        gamma_duration_ms = (
            time.perf_counter_ns() - gamma_started
        ) // 1_000_000
        event = parse_gamma_event(
            gamma_payload,
            expected_slug=slug,
            as_of=datetime.now(timezone.utc).date(),
        )

        book_requests = [
            {"token_id": market.yes_token_id}
            for market in event.markets
        ]
        books_started = time.perf_counter_ns()
        try:
            books_response = self._session.post(
                f"{CLOB_BASE_URL}/books",
                json=book_requests,
                timeout=self._timeout,
            )
        except self._request_exception_types as exc:
            raise PublicApiError("clob_books_request_failed") from exc
        books_payload = self._response_json(
            books_response,
            reason_prefix="clob_books",
        )
        books_duration_ms = (
            time.perf_counter_ns() - books_started
        ) // 1_000_000
        books = parse_clob_books(
            books_payload,
            event=event,
        )
        received_at_ms = time.time_ns() // 1_000_000
        return MarketSnapshot(
            event=event,
            books=books,
            requested_at_ms=requested_at_ms,
            received_at_ms=received_at_ms,
            gamma_duration_ms=int(gamma_duration_ms),
            books_duration_ms=int(books_duration_ms),
        )

    def fetch_stream_bootstrap(
        self,
        event_value: str,
    ) -> MarketStreamBootstrap:
        """Fetch metadata plus all YES/NO books before WebSocket use."""
        slug = extract_event_slug(event_value)
        requested_at_ms = time.time_ns() // 1_000_000
        gamma_started = time.perf_counter_ns()
        try:
            gamma_response = self._session.get(
                f"{GAMMA_BASE_URL}/events/slug/{slug}",
                timeout=self._timeout,
            )
        except self._request_exception_types as exc:
            raise PublicApiError("gamma_request_failed") from exc
        gamma_payload = self._response_json(
            gamma_response,
            reason_prefix="gamma",
        )
        gamma_duration_ms = (
            time.perf_counter_ns() - gamma_started
        ) // 1_000_000
        event = parse_gamma_event(
            gamma_payload,
            expected_slug=slug,
            as_of=datetime.now(timezone.utc).date(),
        )

        book_requests = [
            {"token_id": asset_id}
            for asset_id in event.asset_ids
        ]
        books_started = time.perf_counter_ns()
        try:
            books_response = self._session.post(
                f"{CLOB_BASE_URL}/books",
                json=book_requests,
                timeout=self._timeout,
            )
        except self._request_exception_types as exc:
            raise PublicApiError(
                "clob_books_request_failed"
            ) from exc
        books_payload = self._response_json(
            books_response,
            reason_prefix="clob_books",
        )
        books_duration_ms = (
            time.perf_counter_ns() - books_started
        ) // 1_000_000
        books = parse_clob_asset_books(
            books_payload,
            event=event,
        )
        received_at_ms = time.time_ns() // 1_000_000
        return MarketStreamBootstrap(
            event=event,
            books=books,
            requested_at_ms=requested_at_ms,
            received_at_ms=received_at_ms,
            gamma_duration_ms=int(gamma_duration_ms),
            books_duration_ms=int(books_duration_ms),
        )
