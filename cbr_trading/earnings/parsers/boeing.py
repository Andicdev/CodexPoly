from __future__ import annotations

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
    eps_label,
)


BOEING_CIK = "12927"
BOEING_TICKER = "BA"
BOEING_Q2_2026_CONDITION_ID = (
    "0x9073468de3e2675f39232dfa39ec131c"
    "cb5d181807ce1c56432ebb8c2843100f"
)


class BoeingCoreEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker=BOEING_TICKER,
                cik=BOEING_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(
                    eps_label(
                        r"\bcore\s+(?:earnings(?:\s*/\s*"
                        r"\(?\s*loss\s*\)?)?|loss)\s+per\s+share"
                        r"(?:\s*\(\s*non[\s\u2010-\u2015-]*gaap"
                        r"\s*\)\s*\*?)?"
                    ),
                ),
                parser_name="boeing_core_eps",
                parser_version="1",
                accepted_reason="official_boeing_core_eps",
                missing_reason="boeing_core_eps_not_found",
                conflicting_reason="conflicting_boeing_core_eps_values",
                evidence_title="Boeing official earnings release",
                resolution_basis=(
                    "primary_headline_non_gaap_diluted_eps"
                ),
                forbidden_tails=(
                    "is defined",
                    "for purposes",
                    "most directly comparable",
                    "core operating",
                ),
            )
        )


def ba_q2_2026_shadow_rule() -> EarningsMarketRule:
    return EarningsMarketRule(
        rule_key="ba-2026q2-nongaap-eps-neg0pt32",
        scope_id=earnings_scope_id("BA", 2026, 2),
        ticker="BA",
        cik=BOEING_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T07:30:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("-0.32"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "ba-quarterly-earnings-nongaap-eps-"
            "07-28-2026-neg0pt32"
        ),
        condition_id=BOEING_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "primary_headline_non_gaap_diluted_eps"
            ),
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
            "company_ir": {
                "kind": "rss",
                "provider": "company_ir",
                "feed_url": (
                    "https://investors.boeing.com/"
                    "rss/pressrelease.aspx"
                ),
                "allowed_document_hosts": [
                    "investors.boeing.com",
                ],
                "title_all": [
                    "Boeing",
                    "Second Quarter",
                    "Results",
                ],
                "title_none": ["to release"],
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
