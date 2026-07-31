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
from cbr_trading.earnings.parsers._labelled_eps import (
    LabelledEpsParser,
    LabelledEpsParserConfig,
)


FRANKLIN_RESOURCES_CIK = "38777"
CBOE_GLOBAL_MARKETS_CIK = "1374310"
CHEVRON_CIK = "93410"
COLGATE_PALMOLIVE_CIK = "21665"
MODERNA_CIK = "1682852"
ARES_MANAGEMENT_CIK = "1176948"

FRANKLIN_RESOURCES_Q3_2026_CONDITION_ID = (
    "0xe96fd9c6959d0483dc0cd457db695ba"
    "432fc34c3b210fa5762d550eeebb38e1c"
)
CBOE_GLOBAL_MARKETS_Q2_2026_CONDITION_ID = (
    "0xf9c9b9019399a2ad6422bab7ac142808"
    "52187f84d21d77f0f7f9dc34e76ebee3"
)
CHEVRON_Q2_2026_CONDITION_ID = (
    "0x612ac685fca390b9190dff33d0a273d"
    "0346c9365af9419e39187658e0fe08381"
)
COLGATE_PALMOLIVE_Q2_2026_CONDITION_ID = (
    "0x68386ae98143460fcedbe8db947999d9"
    "167bb610e6c12118e8f79a66250e14ea"
)
MODERNA_Q2_2026_CONDITION_ID = (
    "0x12dd0955557fbc7aa18fbbb535797836"
    "61bbd7443065f421f53429ff60e752cc"
)
ARES_MANAGEMENT_Q2_2026_CONDITION_ID = (
    "0x6fc29d9fc5a9d0955eb8b610b028ccf"
    "38a5c82d33013fc06b261f441fa8ec6c8"
)

_BUSINESSWIRE_EARNINGS_FEED = (
    "https://feed.businesswire.com/rss/home/"
    "?rss=G1QFDERJXkJeGVtQWw=="
)
_PRNEWSWIRE_RSS = (
    "https://www.prnewswire.com/rss/news-releases-list.rss"
)


class FranklinAdjustedDilutedEpsParser(LabelledEpsParser):
    """Parse Franklin Resources' primary adjusted diluted EPS."""

    _CURRENT_PERIOD = re.compile(
        r"\badjusted\s+diluted\s+earnings\s+per\s+share"
        r"(?:\s*\d+)?\s+was\s+\$?"
        r"(?P<value>\d+(?:\.\d+)?)\s+for\s+the\s+quarter\s+ended\s+"
        r"(?P<period>[A-Za-z]+\s+\d{1,2},?\s+20\d{2})\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="BEN",
                cik=FRANKLIN_RESOURCES_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="franklin_adjusted_diluted_eps",
                parser_version="1",
                accepted_reason="official_franklin_adjusted_diluted_eps",
                missing_reason="franklin_adjusted_diluted_eps_not_found",
                conflicting_reason=(
                    "conflicting_franklin_adjusted_diluted_eps"
                ),
                evidence_title="Franklin Resources official earnings release",
                resolution_basis="primary_adjusted_diluted_eps",
                forbidden_prefixes=("guidance", "outlook", "expected"),
                forbidden_tails=("guidance", "outlook", "expected"),
            )
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        expected = rule.period_end.strftime("%B %d, %Y").replace(" 0", " ")
        return tuple(
            (
                Decimal(match.group("value")),
                match.group(0)[:400],
            )
            for match in self._CURRENT_PERIOD.finditer(value)
            if match.group("period").replace(",", "") == expected.replace(",", "")
        )


class CboeAdjustedDilutedEpsParser(LabelledEpsParser):
    """Parse Cboe's current-quarter adjusted diluted EPS."""

    _PATTERNS = (
        re.compile(
            r"\badjusted\s+diluted\s+eps(?:\s*\d+)?\s+"
            r"(?:of|was)\s+\$?(?P<value>\d+(?:\.\d+)?)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\badjusted\s+diluted\s+earnings\s+per\s+common\s+share"
            r"\s+\$?(?P<value>\d+(?:\.\d+)?)\b",
            re.IGNORECASE,
        ),
    )

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="CBOE",
                cik=CBOE_GLOBAL_MARKETS_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="cboe_adjusted_diluted_eps",
                parser_version="1",
                accepted_reason="official_cboe_adjusted_diluted_eps",
                missing_reason="cboe_adjusted_diluted_eps_not_found",
                conflicting_reason=(
                    "conflicting_cboe_adjusted_diluted_eps"
                ),
                evidence_title="Cboe official earnings release",
                resolution_basis="primary_adjusted_diluted_eps",
            )
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        del rule
        return tuple(
            (
                Decimal(match.group("value")),
                match.group(0)[:400],
            )
            for pattern in self._PATTERNS
            for match in pattern.finditer(value)
        )


class ChevronAdjustedDilutedEpsParser(LabelledEpsParser):
    """Parse Chevron's adjusted earnings-per-share summary row."""

    _SUMMARY_ROW = re.compile(
        r"\badjusted\s+earnings\s+per\s+share\s*-\s*diluted"
        r"(?:\s*\(?\s*\d+\s*\)?)?\s*\$/\s*share\s+\$?\s*"
        r"(?P<value>\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="CVX",
                cik=CHEVRON_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="chevron_adjusted_diluted_eps",
                parser_version="1",
                accepted_reason="official_chevron_adjusted_diluted_eps",
                missing_reason="chevron_adjusted_diluted_eps_not_found",
                conflicting_reason=(
                    "conflicting_chevron_adjusted_diluted_eps"
                ),
                evidence_title="Chevron official earnings release",
                resolution_basis=(
                    "earnings_cash_flow_summary_adjusted_eps_diluted"
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
        return tuple(
            (
                Decimal(match.group("value")),
                match.group(0)[:400],
            )
            for match in self._SUMMARY_ROW.finditer(value)
        )


class ColgateBaseBusinessDilutedEpsParser(LabelledEpsParser):
    """Parse Colgate's headline Base Business EPS (diluted)."""

    _HEADLINE_ROW = re.compile(
        r"\bbase\s+business\s+eps\s*\(\s*diluted\s*\)"
        r"\s+\$?\s*(?P<value>\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="CL",
                cik=COLGATE_PALMOLIVE_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="colgate_base_business_diluted_eps",
                parser_version="1",
                accepted_reason=(
                    "official_colgate_base_business_diluted_eps"
                ),
                missing_reason=(
                    "colgate_base_business_diluted_eps_not_found"
                ),
                conflicting_reason=(
                    "conflicting_colgate_base_business_diluted_eps"
                ),
                evidence_title="Colgate-Palmolive official earnings release",
                resolution_basis="primary_base_business_eps_diluted",
            )
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        del rule
        return tuple(
            (
                Decimal(match.group("value")),
                match.group(0)[:400],
            )
            for match in self._HEADLINE_ROW.finditer(value)
        )


class ModernaGaapBasicAndDilutedEpsParser(LabelledEpsParser):
    """Parse Moderna's current-period GAAP basic-and-diluted EPS row."""

    _STATEMENT_ROW = re.compile(
        r"\bnet\s+(?:income|loss)(?:\s+attributable[^|]{0,80})?"
        r"\s+per\s+share\b.{0,120}?\bbasic\s+and\s+diluted\b"
        r"\s+\$?\s*(?P<value>"
        r"\(\s*\d+(?:\.\d+)?\s*\)|-\s*\d+(?:\.\d+)?|"
        r"\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="MRNA",
                cik=MODERNA_CIK,
                metric=EarningsMetric.GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="moderna_gaap_basic_and_diluted_eps",
                parser_version="1",
                accepted_reason=(
                    "official_moderna_gaap_basic_and_diluted_eps"
                ),
                missing_reason=(
                    "moderna_gaap_basic_and_diluted_eps_not_found"
                ),
                conflicting_reason=(
                    "conflicting_moderna_gaap_basic_and_diluted_eps"
                ),
                evidence_title="Moderna official earnings release",
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
        del rule
        found: list[tuple[Decimal, str]] = []
        for match in self._STATEMENT_ROW.finditer(value):
            prefix = value[max(0, match.start() - 80):match.start()]
            if "calculation of" in prefix.casefold():
                continue
            raw = match.group("value").replace(" ", "")
            if raw.startswith("(") and raw.endswith(")"):
                raw = f"-{raw[1:-1]}"
            found.append((Decimal(raw), match.group(0)[:400]))
        return tuple(found)


class AresAfterTaxRealizedIncomePerShareParser(LabelledEpsParser):
    """Parse Ares' primary after-tax realized income per share."""

    _HEADLINE = re.compile(
        r"\bafter-tax\s+realized\s+income\s+per\s+share\s+of\s+"
        r"class\s+a\s+common\s+stock\s+(?:was|of)\s+\$?"
        r"(?P<value>\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="ARES",
                cik=ARES_MANAGEMENT_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="ares_after_tax_realized_income_per_share",
                parser_version="1",
                accepted_reason=(
                    "official_ares_after_tax_realized_income_per_share"
                ),
                missing_reason=(
                    "ares_after_tax_realized_income_per_share_not_found"
                ),
                conflicting_reason=(
                    "conflicting_ares_after_tax_realized_income_per_share"
                ),
                evidence_title="Ares Management official earnings release",
                resolution_basis=(
                    "primary_after_tax_realized_income_per_share"
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
        return tuple(
            (
                Decimal(match.group("value")),
                match.group(0)[:400],
            )
            for match in self._HEADLINE.finditer(value)
        )


def _rule(
    *,
    ticker: str,
    cik: str,
    fiscal_quarter: int,
    estimated_release_at: str,
    metric: EarningsMetric,
    strike: str,
    market_slug: str,
    condition_id: str,
    metric_selection: str,
    public_sources: dict[str, object],
) -> EarningsMarketRule:
    rule = EarningsMarketRule(
        rule_key=(
            f"{ticker.lower()}-2026q{fiscal_quarter}-"
            f"{metric.value.replace('_', '-')}-"
            f"{strike.replace('-', 'neg').replace('.', 'pt')}"
        ),
        scope_id=earnings_scope_id(ticker, 2026, fiscal_quarter),
        ticker=ticker,
        cik=cik,
        fiscal_year=2026,
        fiscal_quarter=fiscal_quarter,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(estimated_release_at),
        metric=metric,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal(strike),
        rounding_places=2,
        currency="USD",
        market_slug=market_slug,
        condition_id=condition_id,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": metric_selection,
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
        },
        fallback_policy={
            "non_gaap_secondary": "seeking_alpha",
            "gaap_secondary": "seeking_alpha",
            "gaap_after_hours": 96,
            "no_release_after_days": 45,
            "gaap_primary_basis": "diluted",
            "gaap_fallback_basis": "basic",
        },
    )
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            **public_sources,
        },
    )


def ben_q3_2026_shadow_rule() -> EarningsMarketRule:
    title_all = ["Franklin Resources", "Third Quarter", "Results"]
    return _rule(
        ticker="BEN",
        cik=FRANKLIN_RESOURCES_CIK,
        fiscal_quarter=3,
        estimated_release_at="2026-07-31T12:30:00+00:00",
        metric=EarningsMetric.NON_GAAP_EPS,
        strike="0.66",
        market_slug=(
            "ben-quarterly-earnings-nongaap-eps-07-31-2026-0pt66"
        ),
        condition_id=FRANKLIN_RESOURCES_Q3_2026_CONDITION_ID,
        metric_selection="primary_adjusted_diluted_eps",
        public_sources={
            "company_ir": {
                "allowed_document_hosts": [
                    "investors.franklinresources.com",
                    "news.franklinresources.com",
                ],
                "feed_url": (
                    "https://investors.franklinresources.com/"
                    "rss/news-releases.xml"
                ),
                "kind": "rss",
                "provider": "company_ir",
                "title_all": title_all,
                "title_none": ["to announce", "conference call"],
            },
            "press_wire": {
                "allowed_document_hosts": ["www.businesswire.com"],
                "feed_url": _BUSINESSWIRE_EARNINGS_FEED,
                "kind": "rss",
                "provider": "businesswire",
                "title_all": title_all,
                "title_none": ["to announce", "conference call"],
            },
        },
    )


def cboe_q2_2026_shadow_rule() -> EarningsMarketRule:
    title_all = ["Cboe", "Second Quarter", "2026", "Results"]
    return _rule(
        ticker="CBOE",
        cik=CBOE_GLOBAL_MARKETS_CIK,
        fiscal_quarter=2,
        estimated_release_at="2026-07-31T11:30:00+00:00",
        metric=EarningsMetric.NON_GAAP_EPS,
        strike="3.49",
        market_slug=(
            "cboe-quarterly-earnings-nongaap-eps-07-31-2026-3pt49"
        ),
        condition_id=CBOE_GLOBAL_MARKETS_Q2_2026_CONDITION_ID,
        metric_selection="primary_adjusted_diluted_eps",
        public_sources={
            "company_ir": {
                "allowed_document_hosts": ["ir.cboe.com"],
                "feed_url": "https://ir.cboe.com/rss/news-releases.xml",
                "kind": "rss",
                "provider": "company_ir",
                "title_all": title_all,
                "title_none": ["announces date", "trading volume"],
            },
            "press_wire": {
                "allowed_document_hosts": ["www.prnewswire.com"],
                "feed_url": _PRNEWSWIRE_RSS,
                "kind": "rss",
                "provider": "prnewswire",
                "title_all": title_all,
                "title_none": ["announces date", "trading volume"],
            },
        },
    )


def cvx_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _rule(
        ticker="CVX",
        cik=CHEVRON_CIK,
        fiscal_quarter=2,
        estimated_release_at="2026-07-31T10:15:00+00:00",
        metric=EarningsMetric.NON_GAAP_EPS,
        strike="5.32",
        market_slug=(
            "cvx-quarterly-earnings-nongaap-eps-07-31-2026-5pt32"
        ),
        condition_id=CHEVRON_Q2_2026_CONDITION_ID,
        metric_selection=(
            "earnings_cash_flow_summary_adjusted_eps_diluted"
        ),
        public_sources={
            "company_ir": {
                "allowed_document_hosts": [
                    "www.chevron.com",
                    "chevron.com",
                ],
                "feed_url": (
                    "https://www.chevron.com/newsroom/archive"
                    "?contenttype=press+release"
                ),
                "kind": "html_listing",
                "listing_utc_offset_minutes": -240,
                "provider": "company_ir",
                "title_all": ["Chevron", "second quarter", "2026", "results"],
                "title_none": ["conference call"],
            },
        },
    )


def cl_q2_2026_shadow_rule() -> EarningsMarketRule:
    title_all = ["Colgate", "2nd Quarter", "2026", "Results"]
    return _rule(
        ticker="CL",
        cik=COLGATE_PALMOLIVE_CIK,
        fiscal_quarter=2,
        estimated_release_at="2026-07-31T11:00:00+00:00",
        metric=EarningsMetric.NON_GAAP_EPS,
        strike="0.95",
        market_slug=(
            "cl-quarterly-earnings-nongaap-eps-07-31-2026-0pt95"
        ),
        condition_id=COLGATE_PALMOLIVE_Q2_2026_CONDITION_ID,
        metric_selection="primary_base_business_eps_diluted",
        public_sources={
            "company_ir": {
                "allowed_document_hosts": [
                    "investor.colgatepalmolive.com",
                ],
                "feed_url": (
                    "https://investor.colgatepalmolive.com/"
                    "rss/news-releases.xml"
                ),
                "kind": "rss",
                "provider": "company_ir",
                "title_all": title_all,
                "title_none": ["webcasts", "conference call"],
            },
            "press_wire": {
                "allowed_document_hosts": ["www.businesswire.com"],
                "feed_url": _BUSINESSWIRE_EARNINGS_FEED,
                "kind": "rss",
                "provider": "businesswire",
                "title_all": title_all,
                "title_none": ["webcasts", "conference call"],
            },
        },
    )


def mrna_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _rule(
        ticker="MRNA",
        cik=MODERNA_CIK,
        fiscal_quarter=2,
        estimated_release_at="2026-07-31T10:30:00+00:00",
        metric=EarningsMetric.GAAP_EPS,
        strike="-2.06",
        market_slug=(
            "mrna-quarterly-earnings-gaap-eps-07-31-2026-neg2pt06"
        ),
        condition_id=MODERNA_Q2_2026_CONDITION_ID,
        metric_selection=(
            "current_period_gaap_basic_and_diluted_eps_row"
        ),
        public_sources={
            "company_ir": {
                "allowed_document_hosts": [
                    "news.modernatx.com",
                    "investors.modernatx.com",
                ],
                "feed_url": (
                    "https://feeds.issuerdirect.com/news.html"
                    "?latest=25&symbol=MRNA"
                ),
                "kind": "html_listing",
                "listing_utc_offset_minutes": -240,
                "provider": "company_ir",
                "title_all": [
                    "Moderna",
                    "Second Quarter",
                    "2026",
                    "Financial Results",
                ],
                "title_none": ["earnings call"],
            },
        },
    )


def ares_q2_2026_shadow_rule() -> EarningsMarketRule:
    title_all = ["Ares Management", "Second Quarter", "2026", "Results"]
    return _rule(
        ticker="ARES",
        cik=ARES_MANAGEMENT_CIK,
        fiscal_quarter=2,
        estimated_release_at="2026-07-31T11:00:00+00:00",
        metric=EarningsMetric.NON_GAAP_EPS,
        strike="1.27",
        market_slug=(
            "ares-quarterly-earnings-nongaap-eps-07-31-2026-1pt27"
        ),
        condition_id=ARES_MANAGEMENT_Q2_2026_CONDITION_ID,
        metric_selection="primary_after_tax_realized_income_per_share",
        public_sources={
            "press_wire": {
                "allowed_document_hosts": ["www.businesswire.com"],
                "feed_url": _BUSINESSWIRE_EARNINGS_FEED,
                "kind": "rss",
                "provider": "businesswire",
                "title_all": title_all,
                "title_none": ["schedules", "updates the time"],
            },
        },
    )


__all__ = [
    "ARES_MANAGEMENT_CIK",
    "ARES_MANAGEMENT_Q2_2026_CONDITION_ID",
    "AresAfterTaxRealizedIncomePerShareParser",
    "CBOE_GLOBAL_MARKETS_CIK",
    "CBOE_GLOBAL_MARKETS_Q2_2026_CONDITION_ID",
    "CHEVRON_CIK",
    "CHEVRON_Q2_2026_CONDITION_ID",
    "COLGATE_PALMOLIVE_CIK",
    "COLGATE_PALMOLIVE_Q2_2026_CONDITION_ID",
    "CboeAdjustedDilutedEpsParser",
    "ChevronAdjustedDilutedEpsParser",
    "ColgateBaseBusinessDilutedEpsParser",
    "FRANKLIN_RESOURCES_CIK",
    "FRANKLIN_RESOURCES_Q3_2026_CONDITION_ID",
    "FranklinAdjustedDilutedEpsParser",
    "MODERNA_CIK",
    "MODERNA_Q2_2026_CONDITION_ID",
    "ModernaGaapBasicAndDilutedEpsParser",
    "ares_q2_2026_shadow_rule",
    "ben_q3_2026_shadow_rule",
    "cboe_q2_2026_shadow_rule",
    "cl_q2_2026_shadow_rule",
    "cvx_q2_2026_shadow_rule",
    "mrna_q2_2026_shadow_rule",
]
