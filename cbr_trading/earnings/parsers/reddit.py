from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from cbr_trading.earnings.contracts import (
    EarningsMarketRule,
    EarningsMetric,
    EpsBasis,
    earnings_scope_id,
)
from cbr_trading.earnings.parsers._common import (
    parse_accounting_decimal,
)
from cbr_trading.earnings.parsers._labelled_eps import (
    LabelledEpsParser,
    LabelledEpsParserConfig,
)


REDDIT_CIK = "1713445"
REDDIT_Q2_2026_CONDITION_ID = (
    "0x6af77208e2962fa9ad5e2b12047d39d0"
    "bd9cfc13a5557621f61b1331638be25f"
)
_REDDIT_IR_LISTING = (
    "https://investor.redditinc.com/news-events/"
    "news-releases/default.aspx"
)
_BUSINESSWIRE_EARNINGS_FEED = (
    "https://feed.businesswire.com/rss/home/"
    "?rss=G1QFDERJXkJeGVtQWw=="
)
_ACCOUNTING_EPS = (
    r"(?P<value>"
    r"\(\s*\$?\s*\d+(?:\.\d+)?\s*\)"
    r"|-\s*\$?\s*\d+(?:\.\d+)?"
    r"|\$?\s*\d+(?:\.\d+)?"
    r")"
)


class RedditGaapDilutedEpsParser(LabelledEpsParser):
    """Parse Reddit's current-quarter GAAP diluted EPS headline."""

    _HEADLINE = re.compile(
        r"\bnet\s+(?P<result>income|loss)\s+of\b"
        r".{0,180}?\bdiluted\s+eps\s+of\s+"
        + _ACCOUNTING_EPS
        + r"\b",
        re.IGNORECASE,
    )
    _PAIR = re.compile(
        r"\bbasic\s+and\s+diluted\s+earnings\s+per\s+share"
        r"(?:\s*\([^)]{1,24}\))?\s+were\s+"
        r"(?P<basic>\(\s*\$?\s*\d+(?:\.\d+)?\s*\)"
        r"|-\s*\$?\s*\d+(?:\.\d+)?"
        r"|\$?\s*\d+(?:\.\d+)?)"
        r"\s+and\s+"
        r"(?P<diluted>\(\s*\$?\s*\d+(?:\.\d+)?\s*\)"
        r"|-\s*\$?\s*\d+(?:\.\d+)?"
        r"|\$?\s*\d+(?:\.\d+)?)"
        r"\s*,?\s+respectively\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="RDDT",
                cik=REDDIT_CIK,
                metric=EarningsMetric.GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="reddit_gaap_diluted_eps",
                parser_version="1",
                accepted_reason="official_reddit_gaap_diluted_eps",
                missing_reason="reddit_gaap_diluted_eps_not_found",
                conflicting_reason=(
                    "conflicting_reddit_gaap_diluted_eps_values"
                ),
                evidence_title="Reddit official earnings release",
                resolution_basis=(
                    "current_quarter_headline_gaap_diluted_eps"
                ),
            )
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        del rule
        found: list[tuple[Decimal, str]] = []
        for match in self._HEADLINE.finditer(value):
            parsed = parse_accounting_decimal(match.group("value"))
            if (
                match.group("result").casefold() == "loss"
                and parsed > 0
            ):
                parsed = -parsed
            found.append((parsed, match.group(0)[:400]))
        found.extend(
            (
                parse_accounting_decimal(match.group("diluted")),
                match.group(0)[:400],
            )
            for match in self._PAIR.finditer(value)
        )
        return tuple(found)


def rddt_q2_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in configuration for the July 30 Reddit market."""

    rule = EarningsMarketRule(
        rule_key="rddt-2026q2-gaap-eps-0pt97",
        scope_id=earnings_scope_id("RDDT", 2026, 2),
        ticker="RDDT",
        cik=REDDIT_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-30T20:08:00+00:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("0.97"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "rddt-quarterly-earnings-gaap-eps-"
            "07-30-2026-0pt97"
        ),
        condition_id=REDDIT_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "current_quarter_headline_gaap_diluted_eps"
            ),
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
        },
        fallback_policy={
            "gaap_secondary": "seeking_alpha",
            "gaap_after_hours": 96,
            "no_release_after_days": 45,
            "gaap_primary_basis": "diluted",
            "gaap_fallback_basis": "basic",
        },
    )
    title_all = [
        "Reddit",
        "Second Quarter",
        "2026",
        "Results",
    ]
    title_none = [
        "to Announce",
        "Conference Call",
    ]
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": [
                    "investor.redditinc.com",
                ],
                "feed_url": _REDDIT_IR_LISTING,
                "kind": "html_listing",
                "listing_utc_offset_minutes": -240,
                "provider": "company_ir",
                "title_all": title_all,
                "title_none": title_none,
            },
            "press_wire": {
                "allowed_document_hosts": [
                    "www.businesswire.com",
                ],
                "feed_url": _BUSINESSWIRE_EARNINGS_FEED,
                "kind": "rss",
                "provider": "businesswire",
                "title_all": title_all,
                "title_none": title_none,
            },
        },
    )
