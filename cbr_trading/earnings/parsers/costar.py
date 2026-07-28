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
from cbr_trading.earnings.parsers._labelled_eps import (
    LabelledEpsParser,
    LabelledEpsParserConfig,
    eps_label,
)
from cbr_trading.earnings.parsers._common import (
    parse_accounting_decimal,
)


COSTAR_CIK = "1057352"
COSTAR_TICKER = "CSGP"
COSTAR_Q2_2026_CONDITION_ID = (
    "0xb71e441b6853dc1c3e1480b6d772b63c"
    "d8a907e706c1b1a4862c3ffa794ac418"
)


class CostarGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker=COSTAR_TICKER,
                cik=COSTAR_CIK,
                metric=EarningsMetric.GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(
                    eps_label(
                        r"\b(?:net\s+)?(?:income|earnings|loss)"
                        r"\s+per\s+diluted\s+share\b"
                    ),
                ),
                parser_name="costar_gaap_diluted_eps",
                parser_version="2",
                accepted_reason="official_costar_gaap_diluted_eps",
                missing_reason="costar_gaap_diluted_eps_not_found",
                conflicting_reason=(
                    "conflicting_costar_gaap_diluted_eps_values"
                ),
                evidence_title="CoStar Group official earnings release",
                resolution_basis="official_gaap_diluted_eps",
                forbidden_prefixes=("adjusted", "non-gaap", "core"),
            )
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        quarter_name = {
            1: "first",
            2: "second",
            3: "third",
            4: "fourth",
        }[rule.fiscal_quarter]
        pattern = re.compile(
            r"\bearnings\s+per\s+diluted\s+share\s+was\s+"
            r"(?P<value>"
            r"\(\s*(?:\$\s*)?\d+(?:\.\d+)?\s*\)"
            r"|-?\s*\$?\s*\d+(?:\.\d+)?"
            r")"
            rf"\s+for\s+the\s+{quarter_name}\s+quarter\s+of\s+"
            rf"{rule.fiscal_year}\b",
            re.IGNORECASE,
        )
        matches: list[tuple[Decimal, str]] = []
        for match in pattern.finditer(value):
            matches.append(
                (
                    parse_accounting_decimal(match.group("value")),
                    match.group(0).strip()[:400],
                )
            )
        return tuple(matches)


def csgp_q2_2026_shadow_rule() -> EarningsMarketRule:
    return EarningsMarketRule(
        rule_key="csgp-2026q2-gaap-eps-0pt10",
        scope_id=earnings_scope_id("CSGP", 2026, 2),
        ticker="CSGP",
        cik=COSTAR_CIK,
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
        strike=Decimal("0.10"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "csgp-quarterly-earnings-gaap-eps-"
            "07-28-2026-0pt1"
        ),
        condition_id=COSTAR_Q2_2026_CONDITION_ID,
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
                    "https://investors.costargroup.com/"
                    "rss/news-releases.xml"
                ),
                "allowed_document_hosts": [
                    "investors.costargroup.com",
                ],
                "title_all": ["CoStar Group", "Q2"],
                "title_none": [
                    "to report",
                    "will report",
                    "conference call",
                ],
            },
        },
        fallback_policy={
            "gaap_secondary": "seeking_alpha",
            "no_release_after_days": 45,
            "gaap_primary_basis": "diluted",
            "gaap_fallback_basis": "basic",
        },
    )
