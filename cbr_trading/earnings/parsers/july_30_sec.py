from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsMarketRule,
    EarningsMetric,
    EarningsParseResult,
    EpsBasis,
    ParseStatus,
    earnings_scope_id,
)
from cbr_trading.earnings.parsers._common import (
    decode_document,
    document_text,
)
from cbr_trading.earnings.parsers._labelled_eps import (
    LabelledEpsParser,
    LabelledEpsParserConfig,
    eps_label,
)


VIRTU_FINANCIAL_CIK = "1592386"
VIRTU_FINANCIAL_Q2_2026_CONDITION_ID = (
    "0xe51d31ccfbad36c133152ce07533e5ba"
    "ee5db4bf2b02f76df7192fce363ac770"
)
MASTERCARD_CIK = "1141391"
MASTERCARD_Q2_2026_CONDITION_ID = (
    "0x9aa5ff923c2669e27ce9be9631deb177"
    "19afd08d877237e9bf24d853b75893a1"
)
YUM_BRANDS_CIK = "1041061"
YUM_BRANDS_Q2_2026_CONDITION_ID = (
    "0xf12f1d26c9f7c02c36e0986be4e32f5a"
    "dc2b30642f0f1f4dda2b5a51bf3e20dd"
)
INTERCONTINENTAL_EXCHANGE_CIK = "1571949"
INTERCONTINENTAL_EXCHANGE_Q2_2026_CONDITION_ID = (
    "0x52f96f0d385691c1534d86c7fbad89ab"
    "d4358da382624b79882279a4ec3eaa20"
)
CIGNA_GROUP_CIK = "1739940"
CIGNA_GROUP_Q2_2026_CONDITION_ID = (
    "0xecdbab51723875aee7d00faa3b5a8adb"
    "bfe7054763dff375c92443a670bb6a61"
)

_GLOBENEWSWIRE_EARNINGS_FEED = (
    "https://www.globenewswire.com/RssFeed/"
    "subjectcode/13-Earnings%20Releases%20And%20"
    "Operating%20Results/feedTitle/GlobeNewswire%20-%20"
    "Earnings%20Releases%20And%20Operating%20Results"
)
_BUSINESSWIRE_EARNINGS_FEED = (
    "https://feed.businesswire.com/rss/home/"
    "?rss=G1QFDERJXkJeGVtQWw=="
)


class VirtuNormalizedAdjustedEpsParser(LabelledEpsParser):
    """Parse Virtu's final Normalized Adjusted EPS, never preliminary data."""

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="VIRT",
                cik=VIRTU_FINANCIAL_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(
                    eps_label(
                        r"\bnormalized\s+adjusted\s+eps"
                        r"(?:\s*\(?\s*\d+\s*\)?)?\s+"
                        r"(?:of|was)\b"
                    ),
                ),
                parser_name="virtu_normalized_adjusted_eps",
                parser_version="1",
                accepted_reason=(
                    "official_virtu_normalized_adjusted_eps"
                ),
                missing_reason=(
                    "virtu_normalized_adjusted_eps_not_found"
                ),
                conflicting_reason=(
                    "conflicting_virtu_normalized_adjusted_eps_values"
                ),
                evidence_title="Virtu official earnings release",
                resolution_basis=(
                    "primary_normalized_adjusted_non_gaap_eps"
                ),
                forbidden_prefixes=(
                    "guidance",
                    "outlook",
                    "expected",
                ),
                forbidden_tails=(
                    "guidance",
                    "outlook",
                    "expected",
                    "subject to revision",
                ),
            )
        )

    def parse(
        self,
        document: str | bytes,
        *,
        source: EarningsDocumentCandidate,
        rule: EarningsMarketRule,
        detected_at: datetime,
    ) -> EarningsParseResult:
        try:
            normalized = document_text(decode_document(document))
        except ValueError:
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="document_encoding_invalid",
            )
        folded = normalized.casefold()
        if (
            "preliminary estimated" in folded
            or "preliminary estimates" in folded
            or "subject to revision" in folded
            or "not a substitute for full financial statements" in folded
        ):
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="virtu_preliminary_results_not_final",
            )
        return super().parse(
            document,
            source=source,
            rule=rule,
            detected_at=detected_at,
        )


class MastercardAdjustedDilutedEpsParser(LabelledEpsParser):
    """Parse Mastercard's primary headline adjusted diluted EPS."""

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="MA",
                cik=MASTERCARD_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(
                    eps_label(
                        r"\badjusted\s+diluted\s+"
                        r"(?:earnings\s+per\s+share|eps)"
                        r"(?:\s*\(?\s*\d+\s*\)?)?\s+"
                        r"(?:of|was)\b"
                    ),
                ),
                parser_name="mastercard_adjusted_diluted_eps",
                parser_version="1",
                accepted_reason=(
                    "official_mastercard_adjusted_diluted_eps"
                ),
                missing_reason=(
                    "mastercard_adjusted_diluted_eps_not_found"
                ),
                conflicting_reason=(
                    "conflicting_mastercard_adjusted_diluted_eps_values"
                ),
                evidence_title="Mastercard official earnings release",
                resolution_basis=(
                    "primary_headline_adjusted_diluted_eps"
                ),
                forbidden_prefixes=(
                    "guidance",
                    "outlook",
                    "expected",
                ),
                forbidden_tails=(
                    "guidance",
                    "outlook",
                    "expected",
                    "most directly comparable",
                ),
            )
        )


class YumEpsExcludingSpecialItemsParser(LabelledEpsParser):
    """Parse YUM's primary headline EPS excluding Special Items."""

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="YUM",
                cik=YUM_BRANDS_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(
                    eps_label(
                        r"\beps\s+excluding\s+special\s+items"
                        r"(?:\s*\(?\s*\d+\s*\)?)?\s+"
                        r"(?:of|was|were)\b"
                    ),
                ),
                parser_name="yum_eps_excluding_special_items",
                parser_version="1",
                accepted_reason=(
                    "official_yum_eps_excluding_special_items"
                ),
                missing_reason=(
                    "yum_eps_excluding_special_items_not_found"
                ),
                conflicting_reason=(
                    "conflicting_yum_eps_excluding_special_items"
                ),
                evidence_title="YUM official earnings release",
                resolution_basis=(
                    "primary_headline_eps_excluding_special_items"
                ),
                forbidden_prefixes=("guidance", "outlook", "expected"),
                forbidden_tails=("guidance", "outlook", "expected"),
            )
        )


class IceAdjustedDilutedEpsParser(LabelledEpsParser):
    """Parse ICE's primary headline adjusted diluted EPS."""

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="ICE",
                cik=INTERCONTINENTAL_EXCHANGE_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(
                    eps_label(
                        r"\badj(?:usted)?\.?\s+diluted\s+eps"
                        r"(?:\s*\(?\s*\d+\s*\)?)?\s+"
                        r"(?:of|was|were)\b"
                    ),
                ),
                parser_name="ice_adjusted_diluted_eps",
                parser_version="1",
                accepted_reason="official_ice_adjusted_diluted_eps",
                missing_reason="ice_adjusted_diluted_eps_not_found",
                conflicting_reason=(
                    "conflicting_ice_adjusted_diluted_eps_values"
                ),
                evidence_title="ICE official earnings release",
                resolution_basis=(
                    "primary_headline_adjusted_diluted_eps"
                ),
                forbidden_prefixes=("guidance", "outlook", "expected"),
                forbidden_tails=("guidance", "outlook", "expected"),
            )
        )


class CignaAdjustedIncomePerShareParser(LabelledEpsParser):
    """Parse Cigna's headline adjusted income from operations per share."""

    _CURRENT_PERIOD = re.compile(
        r"\badjusted\s+income\s+from\s+operations"
        r"(?:\s*\(?\s*\d+\s*\)?)?\s+for\s+"
        r"(?:the\s+)?(?:first|second|1st|2nd)\s+quarter\s+2026"
        r"\s+was\s+\$?[\d,.]+\s+(?:billion|million)\s*,?\s+or\s+"
        r"\$?(?P<value>\d+(?:\.\d+)?)\s+per\s+share\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="CI",
                cik=CIGNA_GROUP_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="cigna_adjusted_income_per_share",
                parser_version="1",
                accepted_reason=(
                    "official_cigna_adjusted_income_per_share"
                ),
                missing_reason=(
                    "cigna_adjusted_income_per_share_not_found"
                ),
                conflicting_reason=(
                    "conflicting_cigna_adjusted_income_per_share_values"
                ),
                evidence_title="Cigna official earnings release",
                resolution_basis=(
                    "primary_headline_adjusted_income_per_share"
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
            for match in self._CURRENT_PERIOD.finditer(value)
        )


def _businesswire_q2_2026_rule(
    *,
    ticker: str,
    cik: str,
    rule_key: str,
    condition_id: str,
    strike: str,
    market_slug: str,
    estimated_release_at: str,
    metric_selection: str,
    title_all: tuple[str, ...],
    title_none: tuple[str, ...],
) -> EarningsMarketRule:
    rule = EarningsMarketRule(
        rule_key=rule_key,
        scope_id=earnings_scope_id(ticker, 2026, 2),
        ticker=ticker,
        cik=cik,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(estimated_release_at),
        metric=EarningsMetric.NON_GAAP_EPS,
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
            "press_wire": {
                "allowed_document_hosts": ["www.businesswire.com"],
                "feed_url": _BUSINESSWIRE_EARNINGS_FEED,
                "kind": "rss",
                "provider": "businesswire",
                "title_all": list(title_all),
                "title_none": list(title_none),
            },
        },
    )


def yum_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _businesswire_q2_2026_rule(
        ticker="YUM",
        cik=YUM_BRANDS_CIK,
        rule_key="yum-2026q2-nongaap-eps-1pt56",
        condition_id=YUM_BRANDS_Q2_2026_CONDITION_ID,
        strike="1.56",
        market_slug=(
            "yum-quarterly-earnings-nongaap-eps-07-30-2026-1pt56"
        ),
        estimated_release_at="2026-07-30T07:00:00-04:00",
        metric_selection="primary_headline_eps_excluding_special_items",
        title_all=("Yum", "Second", "Quarter", "Results"),
        title_none=("Conference Call Details", "to release"),
    )


def ice_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _businesswire_q2_2026_rule(
        ticker="ICE",
        cik=INTERCONTINENTAL_EXCHANGE_CIK,
        rule_key="ice-2026q2-nongaap-eps-1pt84",
        condition_id=INTERCONTINENTAL_EXCHANGE_Q2_2026_CONDITION_ID,
        strike="1.84",
        market_slug=(
            "ice-quarterly-earnings-nongaap-eps-07-30-2026-1pt84"
        ),
        estimated_release_at="2026-07-30T07:30:00-04:00",
        metric_selection="primary_headline_adjusted_diluted_eps",
        title_all=(
            "Intercontinental Exchange",
            "Second Quarter",
            "2026",
        ),
        title_none=("Statistics", "Conference Call"),
    )


def ci_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _businesswire_q2_2026_rule(
        ticker="CI",
        cik=CIGNA_GROUP_CIK,
        rule_key="ci-2026q2-nongaap-eps-7pt60",
        condition_id=CIGNA_GROUP_Q2_2026_CONDITION_ID,
        strike="7.60",
        market_slug=(
            "ci-quarterly-earnings-nongaap-eps-07-30-2026-7pt6"
        ),
        estimated_release_at="2026-07-30T08:30:00-04:00",
        metric_selection=(
            "primary_headline_adjusted_income_per_share"
        ),
        title_all=("Cigna", "Second Quarter", "2026", "Results"),
        title_none=("Conference", "to report"),
    )


def virt_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = EarningsMarketRule(
        rule_key="virt-2026q2-nongaap-eps-1pt82",
        scope_id=earnings_scope_id("VIRT", 2026, 2),
        ticker="VIRT",
        cik=VIRTU_FINANCIAL_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-30T07:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("1.82"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "virt-quarterly-earnings-nongaap-eps-07-30-2026-1pt82"
        ),
        condition_id=VIRTU_FINANCIAL_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "primary_normalized_adjusted_non_gaap_eps"
            ),
            "reject_preliminary_results": True,
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
        },
        fallback_policy={
            "non_gaap_secondary": "seeking_alpha",
            "gaap_after_hours": 96,
            "no_release_after_days": 45,
            "gaap_primary_basis": "diluted",
            "gaap_fallback_basis": "basic",
        },
    )
    title_all = [
        "Virtu",
        "Second Quarter",
        "2026",
        "Results",
    ]
    title_none = [
        "Preliminary",
        "Host Conference Call",
    ]
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": ["ir.virtu.com"],
                "feed_url": (
                    "https://ir.virtu.com/rss/news-releases.xml"
                ),
                "kind": "rss",
                "provider": "company_ir",
                "title_all": title_all,
                "title_none": title_none,
            },
            "press_wire": {
                "allowed_document_hosts": [
                    "www.globenewswire.com"
                ],
                "feed_url": _GLOBENEWSWIRE_EARNINGS_FEED,
                "kind": "rss",
                "provider": "globenewswire",
                "title_all": title_all,
                "title_none": title_none,
            },
        },
    )


def mastercard_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = EarningsMarketRule(
        rule_key="ma-2026q2-nongaap-eps-4pt77",
        scope_id=earnings_scope_id("MA", 2026, 2),
        ticker="MA",
        cik=MASTERCARD_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-30T08:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("4.77"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "ma-quarterly-earnings-nongaap-eps-07-30-2026-4pt77"
        ),
        condition_id=MASTERCARD_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "primary_headline_adjusted_diluted_eps"
            ),
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
        },
        fallback_policy={
            "non_gaap_secondary": "seeking_alpha",
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
            "press_wire": {
                "allowed_document_hosts": [
                    "www.businesswire.com"
                ],
                "feed_url": _BUSINESSWIRE_EARNINGS_FEED,
                "kind": "rss",
                "provider": "businesswire",
                "title_all": [
                    "Mastercard",
                    "Second Quarter",
                    "2026",
                    "Financial Results",
                ],
                "title_none": [
                    "Host Conference Call",
                    "Hosting Conference Call",
                ],
            },
        },
    )


__all__ = [
    "CIGNA_GROUP_CIK",
    "CIGNA_GROUP_Q2_2026_CONDITION_ID",
    "CignaAdjustedIncomePerShareParser",
    "INTERCONTINENTAL_EXCHANGE_CIK",
    "INTERCONTINENTAL_EXCHANGE_Q2_2026_CONDITION_ID",
    "IceAdjustedDilutedEpsParser",
    "MASTERCARD_CIK",
    "MASTERCARD_Q2_2026_CONDITION_ID",
    "MastercardAdjustedDilutedEpsParser",
    "VIRTU_FINANCIAL_CIK",
    "VIRTU_FINANCIAL_Q2_2026_CONDITION_ID",
    "VirtuNormalizedAdjustedEpsParser",
    "YUM_BRANDS_CIK",
    "YUM_BRANDS_Q2_2026_CONDITION_ID",
    "YumEpsExcludingSpecialItemsParser",
    "ci_q2_2026_shadow_rule",
    "ice_q2_2026_shadow_rule",
    "mastercard_q2_2026_shadow_rule",
    "virt_q2_2026_shadow_rule",
    "yum_q2_2026_shadow_rule",
]
