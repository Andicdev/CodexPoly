from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from cbr_trading.earnings.contracts import (
    EarningsMarketRule,
    EarningsMetric,
    EpsBasis,
    earnings_scope_id,
)
from cbr_trading.earnings.parsers._common import (
    ROW_SEPARATOR,
    accounting_values,
    ordered_year_columns,
)
from cbr_trading.earnings.parsers._labelled_eps import (
    LabelledEpsParser,
    LabelledEpsParserConfig,
)


ROBLOX_CIK = "1315098"
ROBLOX_Q2_2026_CONDITION_ID = (
    "0xa12716116eb129272d80f3b85a565f3e"
    "d7efe845bb29f46546187a90b986a7b9"
)
_ROBLOX_IR_LISTING = (
    "https://ir.roblox.com/news/default.aspx"
)
_BUSINESSWIRE_EARNINGS_FEED = (
    "https://feed.businesswire.com/rss/home/"
    "?rss=G1QFDERJXkJeGVtQWw=="
)
_GAAP_EPS_ROW = re.compile(
    r"\bnet\s+(?:income|loss)\s+per\s+share\s+"
    r"attributable\s+to\s+common\s+stockholders\s*,?\s*"
    r"basic\s+and\s+diluted\b",
    re.IGNORECASE,
)
_QUARTER_HEADER = re.compile(
    r"\bthree\s+months\s+ended\b",
    re.IGNORECASE,
)
_CUMULATIVE_HEADER_BY_QUARTER = {
    2: re.compile(r"\bsix\s+months\s+ended\b", re.IGNORECASE),
    3: re.compile(r"\bnine\s+months\s+ended\b", re.IGNORECASE),
    4: re.compile(
        r"\b(?:twelve\s+months|year)\s+ended\b",
        re.IGNORECASE,
    ),
}
_STATEMENT_TITLE = re.compile(
    r"\b(?:condensed\s+)?consolidated\s+statements?\b",
    re.IGNORECASE,
)
_HEADER_LOOKBACK_ROWS = 64


class RobloxGaapDilutedEpsParser(LabelledEpsParser):
    """Parse Roblox's current-period GAAP basic-and-diluted EPS row."""

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="RBLX",
                cik=ROBLOX_CIK,
                metric=EarningsMetric.GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="roblox_gaap_diluted_eps",
                parser_version="3",
                accepted_reason="official_roblox_gaap_diluted_eps",
                missing_reason=(
                    "roblox_gaap_diluted_eps_row_not_found"
                ),
                conflicting_reason=(
                    "conflicting_roblox_gaap_diluted_eps_rows"
                ),
                evidence_title="Roblox official shareholder letter",
                resolution_basis=(
                    "current_period_gaap_basic_and_diluted_eps_row"
                ),
            )
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        found: list[tuple[Decimal, str]] = []
        rows = value.split(ROW_SEPARATOR)
        for row_index, row in enumerate(rows):
            label = _GAAP_EPS_ROW.search(row)
            if label is None:
                continue
            values = accounting_values(row[label.end():])
            if len(values) not in {2, 4}:
                continue
            header_context = self._nearest_header_context(
                rows,
                row_index=row_index,
            )
            if not self._has_safe_column_layout(
                header_context,
                value_count=len(values),
                rule=rule,
            ):
                continue
            # Roblox presents the current-year quarter first and the
            # prior-year comparator second. A cumulative pair, when
            # present, follows the same order.
            found.append((values[0], row.strip()[:400]))
        return tuple(found)

    @staticmethod
    def _nearest_header_context(
        rows: list[str],
        *,
        row_index: int,
    ) -> str:
        lower_bound = max(0, row_index - _HEADER_LOOKBACK_ROWS)
        for candidate_index in range(row_index - 1, lower_bound - 1, -1):
            candidate = rows[candidate_index].strip()
            if not candidate:
                continue
            if _QUARTER_HEADER.search(candidate):
                return " ".join(
                    row.strip()
                    for row in rows[
                        candidate_index:
                        min(row_index, candidate_index + 3)
                    ]
                    if row.strip()
                )
            if _STATEMENT_TITLE.search(candidate):
                break
        return ""

    @staticmethod
    def _has_safe_column_layout(
        header_context: str,
        *,
        value_count: int,
        rule: EarningsMarketRule,
    ) -> bool:
        if _QUARTER_HEADER.search(header_context) is None:
            return False
        if not ordered_year_columns(
            header_context,
            fiscal_year=rule.fiscal_year,
            value_count=value_count,
            current_year_first=True,
        ):
            return False
        if value_count == 2:
            return True
        cumulative_header = _CUMULATIVE_HEADER_BY_QUARTER.get(
            rule.fiscal_quarter
        )
        return bool(
            cumulative_header
            and cumulative_header.search(header_context)
        )


def rblx_q2_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in configuration for the July 30 Roblox market."""

    title_all = [
        "Roblox",
        "Second Quarter",
        "2026",
        "Financial Results",
    ]
    title_none = [
        "to Report",
        "Conference Call",
        "Preliminary",
    ]
    return EarningsMarketRule(
        rule_key="rblx-2026q2-gaap-eps-neg0pt33",
        scope_id=earnings_scope_id("RBLX", 2026, 2),
        ticker="RBLX",
        cik=ROBLOX_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-30T20:00:00+00:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("-0.33"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "rblx-quarterly-earnings-gaap-eps-"
            "07-30-2026-neg0pt33"
        ),
        condition_id=ROBLOX_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "current_period_gaap_basic_and_diluted_eps_row"
            ),
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
            "company_ir": {
                "allowed_document_hosts": [
                    "ir.roblox.com",
                ],
                "feed_url": _ROBLOX_IR_LISTING,
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
        fallback_policy={
            "gaap_secondary": "seeking_alpha",
            "gaap_after_hours": 96,
            "no_release_after_days": 45,
            "gaap_primary_basis": "diluted",
            "gaap_fallback_basis": "basic",
        },
    )
