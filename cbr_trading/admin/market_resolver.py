from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
_CONDITION_ID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class MarketResolverError(RuntimeError):
    """Safe failure while resolving a Polymarket event."""


@dataclass(frozen=True)
class ResolvedMarket:
    direction: str
    condition_id: str
    question: str
    market_id: str
    slug: str
    outcomes: tuple[str, ...]
    token_ids: tuple[str, ...]


@dataclass(frozen=True)
class EventMarketSet:
    event_id: str
    event_slug: str
    event_title: str
    event_url: str
    markets: tuple[ResolvedMarket, ...]

    def by_direction(self) -> dict[str, ResolvedMarket]:
        return {market.direction: market for market in self.markets}


class GammaClient:
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        session: Any | None = None,
    ):
        if timeout <= 0:
            raise ValueError("Gamma timeout must be positive")
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError(
                "The 'requests' package is required for Gamma API."
            ) from exc

        self._requests = requests
        self.timeout = float(timeout)
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "cbr-trading-rule-admin/1.0",
                "Accept": "application/json",
            }
        )

    def get_event_by_slug(self, slug: str) -> dict[str, Any]:
        normalized_slug = extract_event_slug(slug)
        url = f"{GAMMA_BASE_URL}/events/slug/{normalized_slug}"
        try:
            response = self._session.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except self._requests.RequestException as exc:
            raise MarketResolverError(
                "Gamma event request failed: "
                f"{type(exc).__name__}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise MarketResolverError(
                "Gamma event response is not valid JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise MarketResolverError(
                "Gamma event response must be an object"
            )
        return payload


def extract_event_slug(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise MarketResolverError("Polymarket event URL is empty")

    if "://" not in raw:
        slug = raw.strip("/")
    else:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host not in {"polymarket.com", "www.polymarket.com"}:
            raise MarketResolverError(
                "Event URL must use polymarket.com"
            )
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2 or parts[0].lower() != "event":
            raise MarketResolverError(
                "Expected a Polymarket /event/<slug> URL"
            )
        slug = parts[1].lower()

    if not _SLUG_RE.fullmatch(slug):
        raise MarketResolverError("Invalid Polymarket event slug")
    return slug


def resolve_three_way_markets(
    event: Mapping[str, Any],
    *,
    event_url: str,
) -> EventMarketSet:
    raw_markets = event.get("markets")
    if not isinstance(raw_markets, list):
        raise MarketResolverError("Gamma event has no market list")

    resolved: dict[str, ResolvedMarket] = {}
    for raw_market in raw_markets:
        if not isinstance(raw_market, Mapping):
            continue
        if not _is_active(raw_market):
            continue

        question = str(
            raw_market.get("question")
            or raw_market.get("title")
            or ""
        ).strip()
        direction = _classify_direction(question)
        if direction is None:
            raise MarketResolverError(
                f"Cannot classify active market: {question[:120]}"
            )
        if direction in resolved:
            raise MarketResolverError(
                f"Multiple active markets classified as {direction}"
            )

        condition_id = str(
            raw_market.get("conditionId")
            or raw_market.get("condition_id")
            or ""
        ).strip()
        if not _CONDITION_ID_RE.fullmatch(condition_id):
            raise MarketResolverError(
                f"Invalid condition_id for {direction} market"
            )

        outcomes = tuple(
            str(item).strip()
            for item in _parse_list(raw_market.get("outcomes"))
        )
        if {item.lower() for item in outcomes} != {"yes", "no"}:
            raise MarketResolverError(
                f"{direction} market is not binary Yes/No"
            )
        token_ids = tuple(
            str(item).strip()
            for item in _parse_list(
                raw_market.get("clobTokenIds")
                or raw_market.get("clob_token_ids")
            )
        )

        resolved[direction] = ResolvedMarket(
            direction=direction,
            condition_id=condition_id.lower(),
            question=question,
            market_id=str(raw_market.get("id") or "").strip(),
            slug=str(raw_market.get("slug") or "").strip(),
            outcomes=outcomes,
            token_ids=token_ids,
        )

    required = {"decrease", "no_change", "increase"}
    missing = sorted(required - set(resolved))
    if missing:
        raise MarketResolverError(
            "Missing active CBR markets: " + ", ".join(missing)
        )

    event_slug = str(event.get("slug") or "").strip()
    return EventMarketSet(
        event_id=str(event.get("id") or "").strip(),
        event_slug=event_slug,
        event_title=str(event.get("title") or event_slug).strip(),
        event_url=str(event_url).strip(),
        markets=tuple(
            resolved[direction]
            for direction in ("decrease", "no_change", "increase")
        ),
    )


def _is_active(market: Mapping[str, Any]) -> bool:
    return (
        market.get("active") is True
        and market.get("closed") is not True
        and market.get("archived") is not True
    )


def _classify_direction(question: str) -> str | None:
    normalized = " ".join(str(question or "").lower().split())
    if re.search(r"\b(no change|unchanged|keep|remain)\b", normalized):
        return "no_change"
    if re.search(r"\b(decrease|cut|lower|reduce)\b", normalized):
        return "decrease"
    if re.search(r"\b(increase|raise|hike)\b", normalized):
        return "increase"
    return None


def _parse_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []
