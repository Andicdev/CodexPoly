from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from neg_risk_trading.domain import NegRiskContractError


_FEE_CATEGORIES = {
    "crypto_fees_v2": "crypto",
    "sports_fees_v2": "sports",
    "finance_prices_fees": "finance",
    "politics_fees": "politics",
    "economics_fees": "economics",
    "culture_fees": "culture",
    "weather_fees": "weather",
    "general_fees": "general",
    "mentions_fees": "mentions",
    "tech_fees": "tech",
}


@dataclass(frozen=True)
class CatalogEvent:
    event_id: str
    slug: str
    title: str
    active: bool
    closed: bool
    archived: bool
    augmented: bool
    enable_order_book: bool
    end_date: datetime | None
    source_updated_at: datetime | None
    volume: Decimal
    volume_24h: Decimal
    volume_1wk: Decimal
    volume_1mo: Decimal
    volume_1yr: Decimal
    liquidity: Decimal
    open_interest: Decimal
    tags: tuple[Mapping[str, str], ...]


@dataclass(frozen=True)
class CatalogMarket:
    market_id: str
    event_id: str
    condition_id: str
    slug: str
    question: str
    yes_token_id: str | None
    no_token_id: str | None
    neg_risk_other: bool
    accepting_orders: bool
    enable_order_book: bool
    end_date: datetime | None
    source_updated_at: datetime | None
    volume: Decimal
    volume_24h: Decimal
    volume_1wk: Decimal
    volume_1mo: Decimal
    volume_1yr: Decimal
    liquidity: Decimal
    yes_price: Decimal | None
    no_price: Decimal | None
    best_bid: Decimal | None
    best_ask: Decimal | None
    spread: Decimal | None
    tick_size: Decimal | None
    minimum_order_size: Decimal | None
    fees_enabled: bool | None
    fee_type: str | None
    fee_category: str
    fee_rate: Decimal | None
    fee_exponent: int | None
    taker_only: bool | None
    rebate_rate: Decimal | None
    rewards_minimum_size: Decimal | None
    rewards_maximum_spread: Decimal | None
    holding_rewards_enabled: bool
    metadata_complete: bool
    issue_codes: tuple[str, ...]


@dataclass(frozen=True)
class CatalogPage:
    events: tuple[CatalogEvent, ...]
    markets: tuple[CatalogMarket, ...]
    gamma_market_count: int
    neg_risk_market_count: int
    issue_count: int
    skipped_market_count: int
    next_cursor: str | None


def parse_catalog_page(payload: object) -> CatalogPage:
    if not isinstance(payload, Mapping):
        raise NegRiskContractError("catalog_page_invalid")
    raw_markets = payload.get("markets")
    if not isinstance(raw_markets, list):
        raise NegRiskContractError("catalog_markets_missing")
    next_cursor_value = payload.get("next_cursor")
    if next_cursor_value in (None, ""):
        next_cursor = None
    elif isinstance(next_cursor_value, str):
        next_cursor = next_cursor_value.strip() or None
    else:
        raise NegRiskContractError("catalog_cursor_invalid")

    events_by_id: dict[str, CatalogEvent] = {}
    markets: list[CatalogMarket] = []
    neg_risk_market_count = 0
    issue_count = 0
    skipped_market_count = 0
    for raw_value in raw_markets:
        if not isinstance(raw_value, Mapping):
            raise NegRiskContractError(
                "catalog_market_row_invalid"
            )
        if not _is_active_neg_risk_market(raw_value):
            continue
        neg_risk_market_count += 1
        try:
            event_raw = _linked_active_event(raw_value)
            event = _parse_event(event_raw)
            market = _parse_market(
                raw_value,
                event_id=event.event_id,
            )
        except NegRiskContractError:
            issue_count += 1
            skipped_market_count += 1
            continue
        existing = events_by_id.get(event.event_id)
        if existing is not None and existing != event:
            raise NegRiskContractError(
                "catalog_event_metadata_conflict"
            )
        events_by_id[event.event_id] = event
        markets.append(market)
        issue_count += len(market.issue_codes)

    return CatalogPage(
        events=tuple(events_by_id.values()),
        markets=tuple(markets),
        gamma_market_count=len(raw_markets),
        neg_risk_market_count=neg_risk_market_count,
        issue_count=issue_count,
        skipped_market_count=skipped_market_count,
        next_cursor=next_cursor,
    )


def _is_active_neg_risk_market(
    market: Mapping[str, Any],
) -> bool:
    return (
        market.get("negRisk") is True
        and market.get("active") is True
        and market.get("closed") is not True
        and market.get("archived") is not True
    )


def _linked_active_event(
    market: Mapping[str, Any],
) -> Mapping[str, Any]:
    raw_events = market.get("events")
    if not isinstance(raw_events, list):
        raise NegRiskContractError("catalog_event_relation_missing")
    candidates = [
        event
        for event in raw_events
        if isinstance(event, Mapping)
        and event.get("negRisk") is True
    ]
    if len(candidates) != 1:
        raise NegRiskContractError(
            "catalog_event_relation_ambiguous"
        )
    return candidates[0]


def _parse_event(raw: Mapping[str, Any]) -> CatalogEvent:
    event_id = _required_text(
        raw.get("id"),
        reason_code="catalog_event_id_invalid",
    )
    slug = _required_text(
        raw.get("slug"),
        reason_code="catalog_event_slug_invalid",
    )
    title = _required_text(
        raw.get("title"),
        reason_code="catalog_event_title_invalid",
    )
    augmented = raw.get("negRiskAugmented")
    if not isinstance(augmented, bool):
        raise NegRiskContractError(
            "catalog_event_augmented_ambiguous"
        )
    tags: list[Mapping[str, str]] = []
    raw_tags = raw.get("tags")
    if raw_tags is not None:
        if not isinstance(raw_tags, list):
            raise NegRiskContractError("catalog_event_tags_invalid")
        for raw_tag in raw_tags:
            if not isinstance(raw_tag, Mapping):
                raise NegRiskContractError(
                    "catalog_event_tag_invalid"
                )
            tag_id = str(raw_tag.get("id") or "").strip()
            slug_value = str(raw_tag.get("slug") or "").strip()
            label = str(raw_tag.get("label") or "").strip()
            if tag_id and slug_value:
                tags.append(
                    {
                        "id": tag_id,
                        "slug": slug_value,
                        "label": label,
                    }
                )
    return CatalogEvent(
        event_id=event_id,
        slug=slug,
        title=title,
        active=raw.get("active") is True,
        closed=raw.get("closed") is True,
        archived=raw.get("archived") is True,
        augmented=augmented,
        enable_order_book=raw.get("enableOrderBook") is True,
        end_date=_datetime_or_none(raw.get("endDate")),
        source_updated_at=_datetime_or_none(
            raw.get("updatedAt")
        ),
        volume=_nonnegative_decimal(raw.get("volume")),
        volume_24h=_nonnegative_decimal(raw.get("volume24hr")),
        volume_1wk=_nonnegative_decimal(raw.get("volume1wk")),
        volume_1mo=_nonnegative_decimal(raw.get("volume1mo")),
        volume_1yr=_nonnegative_decimal(raw.get("volume1yr")),
        liquidity=_nonnegative_decimal(
            raw.get("liquidityClob")
            if raw.get("liquidityClob") is not None
            else raw.get("liquidity")
        ),
        open_interest=_nonnegative_decimal(
            raw.get("openInterest")
        ),
        tags=tuple(tags),
    )


def _parse_market(
    raw: Mapping[str, Any],
    *,
    event_id: str,
) -> CatalogMarket:
    issues: list[str] = []
    market_id = _required_text(
        raw.get("id"),
        reason_code="catalog_market_id_invalid",
    )
    condition_id = str(raw.get("conditionId") or "").strip().lower()
    if not (
        condition_id.startswith("0x")
        and len(condition_id) == 66
        and all(
            character in "0123456789abcdef"
            for character in condition_id[2:]
        )
    ):
        issues.append("condition_id_invalid")
    outcomes = _array(raw.get("outcomes"))
    token_ids = _array(raw.get("clobTokenIds"))
    yes_token_id: str | None = None
    no_token_id: str | None = None
    if len(outcomes) == 2 and len(token_ids) == 2:
        normalized = [str(value).strip().lower() for value in outcomes]
        if sorted(normalized) == ["no", "yes"]:
            yes_index = normalized.index("yes")
            candidate_yes = str(token_ids[yes_index]).strip()
            candidate_no = str(token_ids[1 - yes_index]).strip()
            if candidate_yes.isdigit() and candidate_no.isdigit():
                yes_token_id = candidate_yes
                no_token_id = candidate_no
    if yes_token_id is None or no_token_id is None:
        issues.append("binary_token_contract_invalid")

    tick_size = _optional_decimal(
        raw.get("orderPriceMinTickSize"),
        issue_code="tick_size_invalid",
        issues=issues,
        positive=True,
    )
    minimum_order_size = _optional_decimal(
        raw.get("orderMinSize"),
        issue_code="minimum_order_size_invalid",
        issues=issues,
        positive=True,
    )
    fee_values = _fee_metadata(raw, issues=issues)
    rewards_minimum_size = _optional_decimal(
        raw.get("rewardsMinSize"),
        issue_code="rewards_minimum_size_invalid",
        issues=issues,
        nonnegative=True,
    )
    rewards_maximum_spread = _optional_decimal(
        raw.get("rewardsMaxSpread"),
        issue_code="rewards_maximum_spread_invalid",
        issues=issues,
        nonnegative=True,
    )
    if (
        rewards_minimum_size is None
        or rewards_maximum_spread is None
    ):
        issues.append("reward_terms_incomplete")

    prices = _array(raw.get("outcomePrices"))
    yes_price: Decimal | None = None
    no_price: Decimal | None = None
    if len(outcomes) == 2 and len(prices) == 2:
        normalized = [str(value).strip().lower() for value in outcomes]
        if sorted(normalized) == ["no", "yes"]:
            yes_index = normalized.index("yes")
            yes_price = _probability_or_none(prices[yes_index])
            no_price = _probability_or_none(prices[1 - yes_index])

    metadata_complete = not any(
        code
        in {
            "condition_id_invalid",
            "binary_token_contract_invalid",
            "tick_size_invalid",
            "minimum_order_size_invalid",
            "fees_enabled_ambiguous",
            "fee_schedule_incomplete",
            "fee_schedule_invalid",
        }
        for code in issues
    )
    return CatalogMarket(
        market_id=market_id,
        event_id=event_id,
        condition_id=condition_id,
        slug=str(raw.get("slug") or "").strip(),
        question=str(raw.get("question") or "").strip(),
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        neg_risk_other=raw.get("negRiskOther") is True,
        accepting_orders=raw.get("acceptingOrders") is True,
        enable_order_book=raw.get("enableOrderBook") is True,
        end_date=_datetime_or_none(raw.get("endDate")),
        source_updated_at=_datetime_or_none(
            raw.get("updatedAt")
        ),
        volume=_nonnegative_decimal(raw.get("volume")),
        volume_24h=_nonnegative_decimal(raw.get("volume24hr")),
        volume_1wk=_nonnegative_decimal(raw.get("volume1wk")),
        volume_1mo=_nonnegative_decimal(raw.get("volume1mo")),
        volume_1yr=_nonnegative_decimal(raw.get("volume1yr")),
        liquidity=_nonnegative_decimal(
            raw.get("liquidityClob")
            if raw.get("liquidityClob") is not None
            else raw.get("liquidity")
        ),
        yes_price=yes_price,
        no_price=no_price,
        best_bid=_probability_or_none(raw.get("bestBid")),
        best_ask=_probability_or_none(raw.get("bestAsk")),
        spread=_nonnegative_optional_decimal(raw.get("spread")),
        tick_size=tick_size,
        minimum_order_size=minimum_order_size,
        fees_enabled=fee_values["fees_enabled"],
        fee_type=fee_values["fee_type"],
        fee_category=fee_values["fee_category"],
        fee_rate=fee_values["fee_rate"],
        fee_exponent=fee_values["fee_exponent"],
        taker_only=fee_values["taker_only"],
        rebate_rate=fee_values["rebate_rate"],
        rewards_minimum_size=rewards_minimum_size,
        rewards_maximum_spread=rewards_maximum_spread,
        holding_rewards_enabled=(
            raw.get("holdingRewardsEnabled") is True
        ),
        metadata_complete=metadata_complete,
        issue_codes=tuple(sorted(set(issues))),
    )


def _fee_metadata(
    raw: Mapping[str, Any],
    *,
    issues: list[str],
) -> dict[str, Any]:
    enabled = raw.get("feesEnabled")
    fee_type_value = str(raw.get("feeType") or "").strip() or None
    if enabled is False and raw.get("feeSchedule") in (None, {}):
        return {
            "fees_enabled": False,
            "fee_type": fee_type_value,
            "fee_category": "fee_free",
            "fee_rate": Decimal("0"),
            "fee_exponent": 1,
            "taker_only": True,
            "rebate_rate": Decimal("0"),
        }
    if enabled is not True:
        issues.append("fees_enabled_ambiguous")
        return _empty_fee_values(
            enabled=None,
            fee_type=fee_type_value,
        )
    schedule = raw.get("feeSchedule")
    if not isinstance(schedule, Mapping):
        issues.append("fee_schedule_incomplete")
        return _empty_fee_values(
            enabled=True,
            fee_type=fee_type_value,
        )
    try:
        fee_rate = _strict_decimal(schedule.get("rate"))
        fee_exponent = int(schedule.get("exponent"))
        rebate_rate = _strict_decimal(
            schedule.get("rebateRate", "0")
        )
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        issues.append("fee_schedule_invalid")
        return _empty_fee_values(
            enabled=True,
            fee_type=fee_type_value,
        )
    taker_only = schedule.get("takerOnly")
    if (
        fee_rate < 0
        or fee_rate > 1
        or fee_exponent < 0
        or rebate_rate < 0
        or rebate_rate > 1
        or not isinstance(taker_only, bool)
    ):
        issues.append("fee_schedule_invalid")
        return _empty_fee_values(
            enabled=True,
            fee_type=fee_type_value,
        )
    return {
        "fees_enabled": True,
        "fee_type": fee_type_value,
        "fee_category": _fee_category(fee_type_value),
        "fee_rate": fee_rate,
        "fee_exponent": fee_exponent,
        "taker_only": taker_only,
        "rebate_rate": rebate_rate,
    }


def _empty_fee_values(
    *,
    enabled: bool | None,
    fee_type: str | None,
) -> dict[str, Any]:
    return {
        "fees_enabled": enabled,
        "fee_type": fee_type,
        "fee_category": _fee_category(fee_type),
        "fee_rate": None,
        "fee_exponent": None,
        "taker_only": None,
        "rebate_rate": None,
    }


def _fee_category(fee_type: str | None) -> str:
    if not fee_type:
        return "unknown"
    return _FEE_CATEGORIES.get(fee_type, "other")


def _array(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        if isinstance(parsed, list):
            return parsed
    return []


def _required_text(value: object, *, reason_code: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise NegRiskContractError(reason_code)
    return result


def _strict_decimal(value: object) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise InvalidOperation
    return result


def _nonnegative_decimal(value: object) -> Decimal:
    result = _nonnegative_optional_decimal(value)
    return result if result is not None else Decimal("0")


def _nonnegative_optional_decimal(
    value: object,
) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = _strict_decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _probability_or_none(value: object) -> Decimal | None:
    result = _nonnegative_optional_decimal(value)
    if result is None or result > 1:
        return None
    return result


def _optional_decimal(
    value: object,
    *,
    issue_code: str,
    issues: list[str],
    positive: bool = False,
    nonnegative: bool = False,
) -> Decimal | None:
    try:
        result = _strict_decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        issues.append(issue_code)
        return None
    if (positive and result <= 0) or (
        nonnegative and result < 0
    ):
        issues.append(issue_code)
        return None
    return result


def _datetime_or_none(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed
