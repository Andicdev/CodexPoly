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


SOFI_CIK = "1818874"
PROCTER_GAMBLE_CIK = "80424"
HUMANA_CIK = "49071"
QUALCOMM_CIK = "804328"
MICROSOFT_CIK = "789019"
META_CIK = "1326801"
EBAY_CIK = "1065088"
ROBINHOOD_CIK = "1783879"

SOFI_Q2_2026_CONDITION_ID = (
    "0xf5e41999c536ba01d79d9b36fadc8b4"
    "beeb5735ac2bd57dfb041145e0d709033"
)
PROCTER_GAMBLE_Q4_2026_CONDITION_ID = (
    "0x161d914e2eda4a1757ad969175add854"
    "146ec6a7cff5627e31040459f5c20725"
)
HUMANA_Q2_2026_CONDITION_ID = (
    "0xdc4eaee1d80f2b50f30d35f6e8209e"
    "2e47dc283de1e77980f399cc206dcb019e"
)
QUALCOMM_Q3_2026_CONDITION_ID = (
    "0xe13b3b5087385775af2dbacd02af3386"
    "acb815b6c8a9d09bc013f158a172ba0a"
)
MICROSOFT_Q4_2026_CONDITION_ID = (
    "0xa7a5a986a14d3c5b47b9892c6aefc48"
    "a85ff3e8e02d999ff7dd015f735ad38d8"
)
META_Q2_2026_CONDITION_ID = (
    "0x5b725d76638a67ec53ced1221dd6140ff"
    "0b419edb72a1653ba4aa82551601704"
)
EBAY_Q2_2026_CONDITION_ID = (
    "0x550698cb57f581259106ad2934b1eb7f"
    "d7bd7f6044f092341773883ebf52f319"
)
ROBINHOOD_Q2_2026_CONDITION_ID = (
    "0x00d480ad192a0cf494a9663a8d0fe225"
    "78b06ea4702f83acfb79bde049a5cf85"
)


def _config(
    *,
    ticker: str,
    cik: str,
    metric: EarningsMetric,
    labels: tuple[str, ...],
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
        label_patterns=tuple(eps_label(label) for label in labels),
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


class SofiGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="SOFI",
                cik=SOFI_CIK,
                metric=EarningsMetric.GAAP_EPS,
                labels=(
                    r"\bdiluted\s+earnings\s+per\s+share\s+"
                    r"(?:reached|was|were|of)\b",
                ),
                parser_name="sofi_gaap_eps",
                accepted_reason="official_sofi_gaap_diluted_eps",
                evidence_title="SoFi official earnings release",
                resolution_basis="reported_gaap_diluted_eps",
            )
        )


class ProcterGambleCoreEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="PG",
                cik=PROCTER_GAMBLE_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                labels=(
                    r"\bapril[\s\u2010-\u2015-]*june\s+quarter\s+"
                    r"results\b.{0,900}?\bcore\s+net\s+earnings\s+"
                    r"per\s+share\s+(?:increased|decreased)"
                    r"[^.;]{0,64}\bto\b",
                ),
                parser_name="procter_gamble_core_eps",
                accepted_reason="official_pg_quarterly_core_eps",
                evidence_title="P&G official earnings release",
                resolution_basis=(
                    "quarterly_primary_headline_non_gaap_core_eps"
                ),
            )
        )


class HumanaAdjustedEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="HUM",
                cik=HUMANA_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                labels=(
                    r"\bon\s+a\s+gaap\s+basis,\s+adjusted\s+eps\s+of\b",
                ),
                parser_name="humana_adjusted_eps",
                accepted_reason="official_humana_adjusted_eps",
                evidence_title="Humana official earnings release",
                resolution_basis="headline_adjusted_non_gaap_eps",
            )
        )


class QualcommNonGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="QCOM",
                cik=QUALCOMM_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                labels=(
                    r"\bgaap\s+eps\s*:\s*(?:\$\s*)?"
                    r"(?:\(\s*\d+(?:\.\d+)?\s*\)|"
                    r"-?\s*\d+(?:\.\d+)?)\s*,\s*"
                    r"non[\s\u2010-\u2015-]*gaap\s+eps\s*:\s*",
                ),
                parser_name="qualcomm_non_gaap_eps",
                accepted_reason="official_qualcomm_non_gaap_eps",
                evidence_title="Qualcomm official earnings release",
                resolution_basis="primary_headline_non_gaap_eps",
            )
        )


class MicrosoftGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="MSFT",
                cik=MICROSOFT_CIK,
                metric=EarningsMetric.GAAP_EPS,
                labels=(
                    r"\bdiluted\s+earnings\s+per\s+share\s+was\b",
                ),
                parser_name="microsoft_gaap_eps",
                accepted_reason="official_microsoft_gaap_diluted_eps",
                evidence_title="Microsoft official earnings release",
                resolution_basis="primary_headline_gaap_diluted_eps",
            )
        )


class MetaGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="META",
                cik=META_CIK,
                metric=EarningsMetric.GAAP_EPS,
                labels=(
                    r"\b(?:first|second|third|fourth)\s+quarter\s+"
                    r"2026\s+financial\s+highlights\b.{0,1500}?"
                    r"\bdiluted\s+earnings\s+per\s+share\s*"
                    r"\(\s*eps\s*\)(?:\s*\(\s*\d+\s*\))?",
                ),
                parser_name="meta_gaap_eps",
                accepted_reason="official_meta_gaap_diluted_eps",
                evidence_title="Meta official earnings release",
                resolution_basis="financial_highlights_gaap_diluted_eps",
            )
        )


class EbayNonGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="EBAY",
                cik=EBAY_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                labels=(
                    r"\bgaap\s+and\s+non[\s\u2010-\u2015-]*gaap\s+"
                    r"earnings\s+per\s+diluted\s+share\s+of\s+"
                    r"(?:\$\s*)?(?:\(\s*\d+(?:\.\d+)?\s*\)|"
                    r"-?\s*\d+(?:\.\d+)?)\s+and\b",
                ),
                parser_name="ebay_non_gaap_eps",
                accepted_reason="official_ebay_non_gaap_diluted_eps",
                evidence_title="eBay official earnings release",
                resolution_basis="primary_headline_non_gaap_diluted_eps",
            )
        )


class RobinhoodGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="HOOD",
                cik=ROBINHOOD_CIK,
                metric=EarningsMetric.GAAP_EPS,
                labels=(
                    r"\bdiluted\s+earnings\s+per\s+share\s*"
                    r"\([^)]*\beps\b[^)]*\)\s+"
                    r"(?:increased|decreased)[^.;]{0,64}\bto\b",
                    r"\bdiluted\s+earnings\s+per\s+share\s*"
                    r"\([^)]*\beps\b[^)]*\)\s+was\b",
                ),
                parser_name="robinhood_gaap_eps",
                accepted_reason="official_robinhood_gaap_diluted_eps",
                evidence_title="Robinhood official earnings release",
                resolution_basis="primary_headline_gaap_diluted_eps",
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
    strike_slug = str(strike).replace("-", "neg").replace(".", "pt")
    return EarningsMarketRule(
        rule_key=(
            f"{ticker.casefold()}-2026q{fiscal_quarter}-"
            f"{metric_slug}-eps-{strike_slug}"
        ),
        scope_id=earnings_scope_id(ticker, 2026, fiscal_quarter),
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


def sofi_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="SOFI",
        cik=SOFI_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T07:00:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        strike=Decimal("0.11"),
        market_slug=(
            "sofi-quarterly-earnings-gaap-eps-07-29-2026-0pt11"
        ),
        condition_id=SOFI_Q2_2026_CONDITION_ID,
        metric_selection="reported_gaap_diluted_eps",
    )


def pg_q4_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="PG",
        cik=PROCTER_GAMBLE_CIK,
        fiscal_quarter=4,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T07:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("1.41"),
        market_slug=(
            "pg-quarterly-earnings-nongaap-eps-07-29-2026-1pt41"
        ),
        condition_id=PROCTER_GAMBLE_Q4_2026_CONDITION_ID,
        metric_selection=(
            "quarterly_primary_headline_non_gaap_core_eps"
        ),
    )


def hum_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="HUM",
        cik=HUMANA_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T06:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("7.00"),
        market_slug=(
            "hum-quarterly-earnings-nongaap-eps-07-29-2026-7"
        ),
        condition_id=HUMANA_Q2_2026_CONDITION_ID,
        metric_selection="headline_adjusted_non_gaap_eps",
    )


def qcom_q3_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="QCOM",
        cik=QUALCOMM_CIK,
        fiscal_quarter=3,
        period_end=date(2026, 6, 28),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T16:05:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("2.23"),
        market_slug=(
            "qcom-quarterly-earnings-nongaap-eps-07-29-2026-2pt23"
        ),
        condition_id=QUALCOMM_Q3_2026_CONDITION_ID,
        metric_selection="primary_headline_non_gaap_eps",
    )


def msft_q4_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="MSFT",
        cik=MICROSOFT_CIK,
        fiscal_quarter=4,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T16:05:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        strike=Decimal("4.21"),
        market_slug=(
            "msft-quarterly-earnings-gaap-eps-07-29-2026-4pt21"
        ),
        condition_id=MICROSOFT_Q4_2026_CONDITION_ID,
        metric_selection="primary_headline_gaap_diluted_eps",
    )


def meta_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="META",
        cik=META_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T16:05:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        strike=Decimal("7.20"),
        market_slug=(
            "meta-quarterly-earnings-gaap-eps-07-29-2026-7pt2"
        ),
        condition_id=META_Q2_2026_CONDITION_ID,
        metric_selection="financial_highlights_gaap_diluted_eps",
    )


def ebay_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="EBAY",
        cik=EBAY_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T16:05:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("1.51"),
        market_slug=(
            "ebay-quarterly-earnings-nongaap-eps-07-29-2026-1pt51"
        ),
        condition_id=EBAY_Q2_2026_CONDITION_ID,
        metric_selection="primary_headline_non_gaap_diluted_eps",
    )


def hood_q2_2026_shadow_rule() -> EarningsMarketRule:
    return _sec_rule(
        ticker="HOOD",
        cik=ROBINHOOD_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T16:05:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        strike=Decimal("0.43"),
        market_slug=(
            "hood-quarterly-earnings-gaap-eps-07-29-2026-0pt43"
        ),
        condition_id=ROBINHOOD_Q2_2026_CONDITION_ID,
        metric_selection="primary_headline_gaap_diluted_eps",
    )
