from __future__ import annotations

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
    eps_label,
)


PAYPAL_CIK = "1633917"
UPS_CIK = "1090727"
HILTON_CIK = "1585689"
INVESCO_CIK = "914208"
COCA_COLA_CIK = "21344"
JETBLUE_CIK = "1158463"
SP_GLOBAL_CIK = "64040"
STARBUCKS_CIK = "829224"
VISA_CIK = "1403161"
FORD_CIK = "37996"

PAYPAL_Q2_2026_CONDITION_ID = (
    "0x886e4e085085f3e22e5d187872d97455"
    "8b5aa8a2b8da97b838891b910328297a"
)
UPS_Q2_2026_CONDITION_ID = (
    "0xf315abadca7a0a77f7c98cb8710dff26"
    "5d5ba5a6324b4aeda8a0bb7ca9e25363"
)
HILTON_Q2_2026_CONDITION_ID = (
    "0x619d7bfd2a712815069f0c8972149287"
    "a6f6fdfe21020d11e721ccd6bf4c3b4f"
)
INVESCO_Q2_2026_CONDITION_ID = (
    "0x82ec63891a948896db5b07aa8c9a69e"
    "3be4dea6aadff8cbffd0235de64add22a"
)
COCA_COLA_Q2_2026_CONDITION_ID = (
    "0xe9bed1463db58e7022ec1c2e2cadb0d8"
    "0d98594095eda33f28f24e4c72a0c13a"
)
JETBLUE_Q2_2026_CONDITION_ID = (
    "0xaf185284cf45118d3b8516b2b999ebaa"
    "447ff2ce5ea98b908381cfc7895cba09"
)
SP_GLOBAL_Q2_2026_CONDITION_ID = (
    "0x58b58b75326faeebe77cbb9ff311e8a7"
    "28af91da3e30a5a6c7407aa2a0c96243"
)
STARBUCKS_Q3_2026_CONDITION_ID = (
    "0xbe6f10dca602f8a71893486557fb94013"
    "03742f51ac4e12eaab55b3fb1bc2a30"
)
VISA_Q3_2026_CONDITION_ID = (
    "0xcda59edf4df94ee2326a0686cc8375ced"
    "c01eca39471a116985019591a83e146"
)
FORD_Q2_2026_CONDITION_ID = (
    "0xdbcc8b389165b2de94773f6074acba1a"
    "c689e2b585ea75dc2ae0980941036900"
)


def _config(
    *,
    ticker: str,
    cik: str,
    metric: EarningsMetric,
    label: str,
    parser_name: str,
    accepted_reason: str,
    evidence_title: str,
    resolution_basis: str,
) -> LabelledEpsParserConfig:
    return LabelledEpsParserConfig(
        ticker=ticker,
        cik=cik,
        metric=metric,
        basis=EpsBasis.DILUTED,
        label_patterns=(eps_label(label),),
        parser_name=parser_name,
        parser_version="1",
        accepted_reason=accepted_reason,
        missing_reason=f"{parser_name}_not_found",
        conflicting_reason=f"conflicting_{parser_name}_values",
        evidence_title=evidence_title,
        resolution_basis=resolution_basis,
        forbidden_tails=(
            "is defined",
            "most directly comparable",
            "not recognized",
        ),
    )


class PayPalNonGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="PYPL",
                cik=PAYPAL_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                label=(
                    r"\bnon[\s\u2010-\u2015-]*gaap\s+eps\s+"
                    r"(?:(?:increased|decreased|grew|declined)"
                    r"[^.;]{0,64}\bto|was)\b"
                ),
                parser_name="paypal_non_gaap_eps",
                accepted_reason="official_paypal_non_gaap_eps",
                evidence_title="PayPal official earnings release",
                resolution_basis="primary_headline_non_gaap_diluted_eps",
            )
        )


class UpsAdjustedDilutedEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="UPS",
                cik=UPS_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                label=(
                    r"\bnon[\s\u2010-\u2015-]*gaap\s+"
                    r"(?:adj\.?|adjusted)\s+diluted\s+"
                    r"(?:eps|earnings\s+per\s+share)\s+"
                    r"(?:of|was|were)\b"
                ),
                parser_name="ups_adjusted_diluted_eps",
                accepted_reason="official_ups_adjusted_diluted_eps",
                evidence_title="UPS official earnings release",
                resolution_basis="reported_non_gaap_diluted_eps",
            )
        )


class HiltonAdjustedDilutedEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="HLT",
                cik=HILTON_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                label=(
                    r"\bdiluted\s+eps,\s+adjusted\s+for\s+"
                    r"special\s+items,\s+was\b"
                ),
                parser_name="hilton_adjusted_diluted_eps",
                accepted_reason="official_hilton_adjusted_diluted_eps",
                evidence_title="Hilton official earnings release",
                resolution_basis=(
                    "reported_diluted_eps_adjusted_for_special_items"
                ),
            )
        )


class InvescoAdjustedDilutedEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="IVZ",
                cik=INVESCO_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                label=(
                    r"\badjusted\s+diluted\s+eps"
                    r"(?:\s*\(\s*\d+\s*\))?\s+of\b"
                ),
                parser_name="invesco_adjusted_diluted_eps",
                accepted_reason="official_invesco_adjusted_diluted_eps",
                evidence_title="Invesco official earnings release",
                resolution_basis="headline_adjusted_diluted_eps",
            )
        )


class CocaColaComparableEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="KO",
                cik=COCA_COLA_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                label=(
                    r"\bcomparable\s+eps\s*"
                    r"\(\s*non[\s\u2010-\u2015-]*gaap\s*\)\s+"
                    r"(?:grew|declined|increased|decreased)"
                    r"[^.;]{0,64}\bto\b"
                ),
                parser_name="coca_cola_comparable_eps",
                accepted_reason="official_coca_cola_comparable_eps",
                evidence_title="Coca-Cola official earnings release",
                resolution_basis="headline_comparable_non_gaap_eps",
            )
        )


class JetBlueAdjustedDilutedEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="JBLU",
                cik=JETBLUE_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                label=(
                    r"\bdiluted\s+excluding\s+special\s+items"
                    r"\s+and\s+gain\s+on\s+investments\b"
                ),
                parser_name="jetblue_adjusted_diluted_eps",
                accepted_reason="official_jetblue_adjusted_diluted_eps",
                evidence_title="JetBlue official earnings release",
                resolution_basis=(
                    "diluted_eps_excluding_special_items_and_investments"
                ),
            )
        )


class SpGlobalAdjustedDilutedEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="SPGI",
                cik=SP_GLOBAL_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                label=(
                    r"\badjusted\s+diluted\s+earnings\s+per\s+share"
                    r"\s+(?:increased|decreased)"
                    r"[^.;]{0,64}\bto\b"
                ),
                parser_name="sp_global_adjusted_diluted_eps",
                accepted_reason="official_sp_global_adjusted_diluted_eps",
                evidence_title="S&P Global official earnings release",
                resolution_basis="reported_adjusted_diluted_eps",
            )
        )


class StarbucksGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="SBUX",
                cik=STARBUCKS_CIK,
                metric=EarningsMetric.GAAP_EPS,
                label=r"\bq[1-4]\s+gaap\s+eps\b",
                parser_name="starbucks_gaap_eps",
                accepted_reason="official_starbucks_gaap_eps",
                evidence_title="Starbucks official earnings release",
                resolution_basis="primary_headline_gaap_diluted_eps",
            )
        )


class VisaNonGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="V",
                cik=VISA_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                label=(
                    r"\bnon[\s\u2010-\u2015-]*gaap\s+"
                    r"earnings\s+per\s+share"
                    r"(?:\s*\(\s*\d+\s*\))?\s*\$"
                ),
                parser_name="visa_non_gaap_eps",
                accepted_reason="official_visa_non_gaap_eps",
                evidence_title="Visa official earnings release",
                resolution_basis="headline_non_gaap_diluted_eps",
            )
        )


class FordAdjustedDilutedEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="F",
                cik=FORD_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                label=(
                    r"\badjusted\s+earnings\s+per\s+share\s*"
                    r"[\u2010-\u2015-]\s*diluted\s*"
                    r"\(\s*non[\s\u2010-\u2015-]*gaap\s*\)"
                ),
                parser_name="ford_adjusted_diluted_eps",
                accepted_reason="official_ford_adjusted_diluted_eps",
                evidence_title="Ford official earnings release",
                resolution_basis="adjusted_non_gaap_diluted_eps",
            )
        )


def _sec_rule(
    *,
    ticker: str,
    cik: str,
    fiscal_quarter: int,
    period_end: date,
    estimated_release_at: datetime,
    metric: EarningsMetric,
    strike: Decimal,
    market_slug: str,
    condition_id: str,
    metric_selection: str,
) -> EarningsMarketRule:
    metric_slug = (
        "gaap" if metric is EarningsMetric.GAAP_EPS else "nongaap"
    )
    strike_slug = (
        str(strike)
        .replace("-", "neg")
        .replace(".", "pt")
    )
    return EarningsMarketRule(
        rule_key=(
            f"{ticker.casefold()}-2026q{fiscal_quarter}-"
            f"{metric_slug}-eps-{strike_slug}"
        ),
        scope_id=earnings_scope_id(
            ticker,
            2026,
            fiscal_quarter,
        ),
        ticker=ticker,
        cik=cik,
        fiscal_year=2026,
        fiscal_quarter=fiscal_quarter,
        period_end=period_end,
        estimated_release_at=estimated_release_at,
        metric=metric,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=strike,
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
            (
                "gaap_secondary"
                if metric is EarningsMetric.GAAP_EPS
                else "non_gaap_secondary"
            ): "seeking_alpha",
            "gaap_after_hours": 96,
            "no_release_after_days": 45,
            "gaap_primary_basis": "diluted",
            "gaap_fallback_basis": "basic",
        },
    )


def pypl_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="PYPL",
        cik=PAYPAL_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T07:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("1.28"),
        market_slug=(
            "pypl-quarterly-earnings-nongaap-eps-"
            "07-28-2026-1pt28"
        ),
        condition_id=PAYPAL_Q2_2026_CONDITION_ID,
        metric_selection="primary_headline_non_gaap_diluted_eps",
    )


def ups_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="UPS",
        cik=UPS_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T06:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("1.66"),
        market_slug=(
            "ups-quarterly-earnings-nongaap-eps-"
            "07-28-2026-1pt66"
        ),
        condition_id=UPS_Q2_2026_CONDITION_ID,
        metric_selection="reported_non_gaap_diluted_eps",
    )


def hlt_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = _sec_rule(
        ticker="HLT",
        cik=HILTON_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T06:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("2.25"),
        market_slug=(
            "hlt-quarterly-earnings-nongaap-eps-"
            "07-28-2026-2pt25"
        ),
        condition_id=HILTON_Q2_2026_CONDITION_ID,
        metric_selection=(
            "reported_diluted_eps_adjusted_for_special_items"
        ),
    )
    return replace(
        rule,
        source_policy={
            **dict(rule.source_policy),
            "company_ir": {
                "kind": "rss",
                "provider": "company_ir",
                "feed_url": "https://stories.hilton.com/feed/",
                "allowed_document_hosts": ["stories.hilton.com"],
                "title_all": [
                    "Hilton",
                    "Second Quarter",
                    "Results",
                ],
                "title_none": [
                    "Announces",
                    "Release Date",
                ],
            },
        },
    )


def ivz_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="IVZ",
        cik=INVESCO_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T07:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("0.66"),
        market_slug=(
            "ivz-quarterly-earnings-nongaap-eps-"
            "07-28-2026-0pt66"
        ),
        condition_id=INVESCO_Q2_2026_CONDITION_ID,
        metric_selection="headline_adjusted_diluted_eps",
    )


def ko_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="KO",
        cik=COCA_COLA_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 7, 3),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T06:55:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("0.93"),
        market_slug=(
            "ko-quarterly-earnings-nongaap-eps-"
            "07-28-2026-0pt93"
        ),
        condition_id=COCA_COLA_Q2_2026_CONDITION_ID,
        metric_selection="headline_comparable_non_gaap_eps",
    )


def jblu_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="JBLU",
        cik=JETBLUE_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T06:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("-0.68"),
        market_slug=(
            "jblu-quarterly-earnings-nongaap-eps-"
            "07-28-2026-neg0pt68"
        ),
        condition_id=JETBLUE_Q2_2026_CONDITION_ID,
        metric_selection=(
            "diluted_eps_excluding_special_items_and_investments"
        ),
    )


def spgi_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="SPGI",
        cik=SP_GLOBAL_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T07:15:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("4.95"),
        market_slug=(
            "spgi-quarterly-earnings-nongaap-eps-"
            "07-28-2026-4pt95"
        ),
        condition_id=SP_GLOBAL_Q2_2026_CONDITION_ID,
        metric_selection="reported_adjusted_diluted_eps",
    )


def sbux_q3_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="SBUX",
        cik=STARBUCKS_CIK,
        fiscal_quarter=3,
        period_end=date(2026, 6, 28),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T16:05:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        strike=Decimal("0.69"),
        market_slug=(
            "sbux-quarterly-earnings-gaap-eps-"
            "07-28-2026-0pt69"
        ),
        condition_id=STARBUCKS_Q3_2026_CONDITION_ID,
        metric_selection="primary_headline_gaap_diluted_eps",
    )


def visa_q3_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="V",
        cik=VISA_CIK,
        fiscal_quarter=3,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T16:05:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("3.22"),
        market_slug=(
            "v-quarterly-earnings-nongaap-eps-"
            "07-28-2026-3pt22"
        ),
        condition_id=VISA_Q3_2026_CONDITION_ID,
        metric_selection="headline_non_gaap_diluted_eps",
    )


def ford_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="F",
        cik=FORD_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T16:05:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("0.35"),
        market_slug=(
            "f-quarterly-earnings-nongaap-eps-"
            "07-28-2026-0pt35"
        ),
        condition_id=FORD_Q2_2026_CONDITION_ID,
        metric_selection="adjusted_non_gaap_diluted_eps",
    )
