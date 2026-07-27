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


CAESARS_CIK = "1590895"
CAESARS_TICKER = "CZR"
CAESARS_Q2_2026_CONDITION_ID = (
    "0x13805b2ba317a2c26ff596bb59534c23"
    "c4808fd26eac9be6f847977b92fd6bf3"
)


class CaesarsGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker=CAESARS_TICKER,
                cik=CAESARS_CIK,
                metric=EarningsMetric.GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(
                    eps_label(
                        r"\bdiluted\s+(?:net\s+)?"
                        r"(?:earnings|income|loss)\s+per\s+share\b"
                    ),
                    eps_label(
                        r"\b(?:earnings|income|loss)\s+per\s+share"
                        r"\s*[-\u2013]\s*diluted\b"
                    ),
                ),
                parser_name="caesars_gaap_diluted_eps",
                parser_version="1",
                accepted_reason="official_caesars_gaap_diluted_eps",
                missing_reason="caesars_gaap_diluted_eps_not_found",
                conflicting_reason=(
                    "conflicting_caesars_gaap_diluted_eps_values"
                ),
                evidence_title=(
                    "Caesars Entertainment official earnings release"
                ),
                resolution_basis="official_gaap_diluted_eps",
                forbidden_prefixes=("adjusted", "non-gaap", "core"),
            )
        )


def czr_q2_2026_shadow_rule() -> EarningsMarketRule:
    return EarningsMarketRule(
        rule_key="czr-2026q2-gaap-eps-0pt05",
        scope_id=earnings_scope_id("CZR", 2026, 2),
        ticker="CZR",
        cik=CAESARS_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T16:05:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("0.05"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "czr-quarterly-earnings-gaap-eps-"
            "07-28-2026-0pt05"
        ),
        condition_id=CAESARS_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": "official_gaap_diluted_eps",
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
            "company_ir": {
                "kind": "rss",
                "provider": "company_ir",
                "feed_url": (
                    "https://investor.caesars.com/"
                    "rss/news-releases.xml"
                ),
                "allowed_document_hosts": [
                    "investor.caesars.com",
                ],
                "title_all": [
                    "Caesars Entertainment",
                    "Second Quarter",
                    "Results",
                ],
                "title_none": ["to report"],
            },
        },
        fallback_policy={
            "gaap_secondary": "seeking_alpha",
            "no_release_after_days": 45,
            "gaap_primary_basis": "diluted",
            "gaap_fallback_basis": "basic",
        },
    )
