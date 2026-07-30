from __future__ import annotations

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

_GLOBENEWSWIRE_EARNINGS_FEED = (
    "https://www.globenewswire.com/RssFeed/"
    "subjectcode/13-Earnings%20Releases%20And%20"
    "Operating%20Results/feedTitle/GlobeNewswire%20-%20"
    "Earnings%20Releases%20And%20Operating%20Results"
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


__all__ = [
    "VIRTU_FINANCIAL_CIK",
    "VIRTU_FINANCIAL_Q2_2026_CONDITION_ID",
    "VirtuNormalizedAdjustedEpsParser",
    "virt_q2_2026_shadow_rule",
]
