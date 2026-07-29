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
    eps_label,
)
from cbr_trading.earnings.parsers._common import (
    ROW_SEPARATOR,
    accounting_values,
    parse_accounting_decimal,
)


SOFI_CIK = "1818874"
PROCTER_GAMBLE_CIK = "80424"
HUMANA_CIK = "49071"
WINGSTOP_CIK = "1636222"
ARES_CAPITAL_CIK = "1287750"
INTEGRA_LIFESCIENCES_CIK = "917520"
GARMIN_CIK = "1121788"
CBRE_CIK = "1138118"
PENSKE_AUTOMOTIVE_CIK = "1019849"
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
WINGSTOP_Q2_2026_CONDITION_ID = (
    "0x364b6da0b6c766eb072c3be8ded36b6"
    "fc39e5b8c831346fd2e277d2c1d07714a"
)
ARES_CAPITAL_Q2_2026_CONDITION_ID = (
    "0xc1d7ebaa2951adedf0e111c0555e29426"
    "755d005dedb43ce71bf7d1c065a22b8"
)
INTEGRA_LIFESCIENCES_Q2_2026_CONDITION_ID = (
    "0x105f7e63b07c079be5e52a3c15ba8ce1"
    "5022c45b189ea9a54d23c31bd972eb1f"
)
GARMIN_Q2_2026_CONDITION_ID = (
    "0xa8799cc9d0d491c736c76d6906e9cf9c"
    "f10913d285bcf50ca834ff4d50753116"
)
CBRE_Q2_2026_CONDITION_ID = (
    "0x27211249b8125a43a4b850ce763030142"
    "709ee1402ebac8b3a8543bee0cd9d22"
)
PENSKE_AUTOMOTIVE_Q2_2026_CONDITION_ID = (
    "0xdb3c1e0e76010fb23f1c29d2adf701c"
    "1e56eadc2d0d45282863296367ba64e71"
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
    parser_version: str = "1",
    forbidden_prefixes: tuple[str, ...] = (),
    forbidden_tails: tuple[str, ...] = (),
) -> LabelledEpsParserConfig:
    return LabelledEpsParserConfig(
        ticker=ticker,
        cik=cik,
        metric=metric,
        basis=EpsBasis.DILUTED,
        label_patterns=tuple(eps_label(label) for label in labels),
        parser_name=parser_name,
        parser_version=parser_version,
        accepted_reason=accepted_reason,
        missing_reason=f"{parser_name}_not_found",
        conflicting_reason=f"conflicting_{parser_name}_values",
        evidence_title=evidence_title,
        resolution_basis=resolution_basis,
        forbidden_prefixes=forbidden_prefixes,
        forbidden_tails=(
            "is defined",
            "most directly comparable",
            "not recognized",
        ) + forbidden_tails,
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


class WingstopGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="WING",
                cik=WINGSTOP_CIK,
                metric=EarningsMetric.GAAP_EPS,
                labels=(
                    r"\bnet\s+income\s+of\s+(?:\$\s*)?"
                    r"\d+(?:\.\d+)?\s+million,\s+or\b",
                    r"\bnet\s+income\s*,\s*"
                    r"(?:increased|decreased)\b"
                    r".{0,100}?\bor\b",
                ),
                parser_name="wingstop_gaap_eps",
                parser_version="2",
                accepted_reason="official_wingstop_gaap_diluted_eps",
                evidence_title="Wingstop official earnings release",
                resolution_basis="headline_gaap_diluted_eps",
            )
        )


class AresCapitalCoreEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="ARCC",
                cik=ARES_CAPITAL_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                labels=(
                    r"\bcore\s+eps(?:\s*\(\s*\d+\s*\))?",
                ),
                parser_name="ares_capital_core_eps",
                parser_version="2",
                accepted_reason="official_ares_capital_core_eps",
                evidence_title="Ares Capital official earnings release",
                resolution_basis="operating_results_core_eps",
                forbidden_tails=(
                    "guidance",
                    "outlook",
                    "expected",
                ),
            )
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        quarter = int(rule.fiscal_quarter)
        current_year = str(rule.fiscal_year)[-2:]
        prior_year = str(rule.fiscal_year - 1)[-2:]
        header = re.search(
            rf"\bq{quarter}\s*-\s*{current_year}\b"
            rf".{{0,200}}\bq{quarter}\s*-\s*{prior_year}\b",
            value,
            re.IGNORECASE,
        )
        if header is None:
            return ()
        window_start = header.end()
        window_end = min(len(value), window_start + 4000)
        label = re.search(
            r"\bcore\s+eps(?:\s*\(\s*\d+\s*\))?",
            value[window_start:window_end],
            re.IGNORECASE,
        )
        if label is None:
            return ()
        label_start = window_start + label.start()
        label_end = window_start + label.end()
        row_end = value.find(ROW_SEPARATOR, label_end)
        tail_end = (
            row_end
            if row_end >= 0
            else min(window_end, label_end + 240)
        )
        values = accounting_values(value[label_end:tail_end])
        if len(values) < 2:
            return ()
        excerpt = value[label_start:tail_end].strip()[:400]
        return ((values[0], excerpt),)


class IntegraAdjustedDilutedEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="IART",
                cik=INTEGRA_LIFESCIENCES_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                labels=(
                    r"\badjusted\s+earnings\s+per\s+diluted\s+"
                    r"share\s+of\b",
                    r"\badjusted\s+diluted\s+net\s+income\s+"
                    r"per\s+share\b",
                ),
                parser_name="integra_adjusted_diluted_eps",
                accepted_reason="official_integra_adjusted_diluted_eps",
                evidence_title="Integra LifeSciences official earnings release",
                resolution_basis="reported_adjusted_diluted_eps",
            )
        )


class GarminProFormaDilutedEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="GRMN",
                cik=GARMIN_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                labels=(
                    r"\bpro\s+forma\s+eps(?:\s*\(\s*\d+\s*\))?"
                    r"\s+of\b",
                    r"\bpro\s+forma\s+diluted\s+eps"
                    r"(?:\s*\(\s*\d+\s*\))?\b",
                ),
                parser_name="garmin_pro_forma_diluted_eps",
                accepted_reason="official_garmin_pro_forma_diluted_eps",
                evidence_title="Garmin official earnings release",
                resolution_basis="reported_pro_forma_diluted_eps",
            )
        )


class CbreGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="CBRE",
                cik=CBRE_CIK,
                metric=EarningsMetric.GAAP_EPS,
                labels=(
                    r"\bgaap\s+eps\s+(?:up|down)"
                    r"[^.;]{0,64}\bto\b",
                    r"\bkey\s+highlights\s*:\s*"
                    r"gaap\s+eps\s+of\b",
                ),
                parser_name="cbre_gaap_eps",
                parser_version="2",
                accepted_reason="official_cbre_gaap_diluted_eps",
                evidence_title="CBRE official earnings release",
                resolution_basis="headline_gaap_diluted_eps",
            )
        )


class PenskeAutomotiveGaapEpsParser(LabelledEpsParser):
    def __init__(self) -> None:
        super().__init__(
            _config(
                ticker="PAG",
                cik=PENSKE_AUTOMOTIVE_CIK,
                metric=EarningsMetric.GAAP_EPS,
                labels=(
                    r"(?<!adjusted\s)\bearnings\s+per\s+share\s+of\b",
                    r"\brelated\s+earnings\s+per\s+share\s+was\b",
                ),
                parser_name="penske_automotive_gaap_eps",
                parser_version="2",
                accepted_reason=(
                    "official_penske_automotive_gaap_diluted_eps"
                ),
                evidence_title=(
                    "Penske Automotive official earnings release"
                ),
                resolution_basis="reported_gaap_diluted_eps",
                forbidden_prefixes=(
                    "adjusted",
                    "expected",
                    "guidance",
                ),
            )
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        pattern = re.compile(
            r"\bfor\s+the\s+quarter\b"
            r".{0,1200}?"
            r"\band\s+related\s+earnings\s+per\s+share\s+was\s+"
            r"(?P<value>"
            r"\(\s*(?:\$\s*)?\d+(?:\.\d+)?\s*\)"
            r"|-?\s*\$?\s*\d+(?:\.\d+)?"
            r")"
            r"\s+compared\s+to\b",
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


def _businesswire_policy(
    *,
    title_all: tuple[str, ...],
    title_none: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "allowed_document_hosts": ["www.businesswire.com"],
        "feed_url": (
            "https://feed.businesswire.com/rss/home/"
            "?rss=G1QFDERJXkJeGVtQWw=="
        ),
        "kind": "rss",
        "provider": "businesswire",
        "title_all": list(title_all),
        "title_none": list(title_none),
    }


def sofi_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = _sec_rule(
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
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "press_wire": _businesswire_policy(
                title_all=(
                    "SoFi",
                    "Reports Second Quarter",
                    "2026",
                ),
                title_none=("Schedules",),
            ),
        },
    )


def pg_q4_2026_shadow_rule() -> EarningsMarketRule:
    rule = _sec_rule(
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
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "press_wire": _businesswire_policy(
                title_all=(
                    "P&G",
                    "Fourth Quarter",
                    "Fiscal Year 2026",
                    "Results",
                ),
                title_none=("Webcast",),
            ),
        },
    )


def hum_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = _sec_rule(
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
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": ["humana.gcs-web.com"],
                "feed_url": (
                    "https://humana.gcs-web.com/"
                    "rss/news-releases.xml"
                ),
                "kind": "rss",
                "provider": "company_ir",
                "title_all": [
                    "Humana",
                    "Second Quarter",
                    "Financial Results",
                ],
                "title_none": ["to release"],
            },
        },
    )


def wing_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = _sec_rule(
        ticker="WING",
        cik=WINGSTOP_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 27),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T07:45:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        strike=Decimal("1.03"),
        market_slug=(
            "wing-quarterly-earnings-gaap-eps-07-29-2026-1pt03"
        ),
        condition_id=WINGSTOP_Q2_2026_CONDITION_ID,
        metric_selection="headline_gaap_diluted_eps",
    )
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": ["ir.wingstop.com"],
                "feed_url": "https://ir.wingstop.com/feed/",
                "kind": "rss",
                "provider": "company_ir",
                "title_all": [
                    "Wingstop",
                    "Second Quarter",
                    "Financial Results",
                ],
                "title_none": ["to announce"],
            },
            "press_wire": {
                "allowed_document_hosts": ["www.prnewswire.com"],
                "feed_url": (
                    "https://www.prnewswire.com/rss/"
                    "news-releases-list.rss"
                ),
                "kind": "rss",
                "provider": "prnewswire",
                "title_all": [
                    "Wingstop",
                    "Second Quarter",
                    "Financial Results",
                ],
                "title_none": ["to announce"],
            },
        },
    )


def arcc_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = _sec_rule(
        ticker="ARCC",
        cik=ARES_CAPITAL_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T07:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("0.47"),
        market_slug=(
            "arcc-quarterly-earnings-nongaap-eps-07-29-2026-0pt47"
        ),
        condition_id=ARES_CAPITAL_Q2_2026_CONDITION_ID,
        metric_selection="operating_results_core_eps",
    )
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "press_wire": _businesswire_policy(
                title_all=(
                    "Ares Capital Corporation",
                    "June 30, 2026",
                    "Financial Results",
                ),
                title_none=("Schedules",),
            ),
        },
    )


def iart_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = _sec_rule(
        ticker="IART",
        cik=INTEGRA_LIFESCIENCES_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T06:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("0.48"),
        market_slug=(
            "iart-quarterly-earnings-nongaap-eps-07-29-2026-0pt48"
        ),
        condition_id=INTEGRA_LIFESCIENCES_Q2_2026_CONDITION_ID,
        metric_selection="reported_adjusted_diluted_eps",
    )
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": [
                    "investor.integralife.com"
                ],
                "feed_url": (
                    "https://investor.integralife.com/"
                    "rss/news-releases.xml"
                ),
                "kind": "rss",
                "provider": "company_ir",
                "title_all": [
                    "Integra LifeSciences",
                    "Second Quarter",
                    "Financial Results",
                ],
                "title_none": ["to host"],
            },
            "press_wire": {
                "allowed_document_hosts": [
                    "www.globenewswire.com"
                ],
                "feed_url": (
                    "https://www.globenewswire.com/RssFeed/"
                    "subjectcode/13-Earnings%20Releases%20And%20"
                    "Operating%20Results/feedTitle/GlobeNewswire%20-%20"
                    "Earnings%20Releases%20And%20Operating%20Results"
                ),
                "kind": "rss",
                "provider": "globenewswire",
                "title_all": [
                    "Integra LifeSciences",
                    "Second Quarter",
                    "Financial Results",
                ],
                "title_none": ["to host"],
            },
        },
    )


def grmn_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = _sec_rule(
        ticker="GRMN",
        cik=GARMIN_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 27),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T07:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        strike=Decimal("2.29"),
        market_slug=(
            "grmn-quarterly-earnings-nongaap-eps-07-29-2026-2pt29"
        ),
        condition_id=GARMIN_Q2_2026_CONDITION_ID,
        metric_selection="reported_pro_forma_diluted_eps",
    )
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": ["www.garmin.com"],
                "feed_url": (
                    "https://www.garmin.com/en-US/newsroom/feed/"
                ),
                "kind": "rss",
                "provider": "company_ir",
                "title_all": [
                    "Garmin",
                    "Second Quarter",
                    "2026",
                    "Results",
                ],
                "title_none": ["schedules"],
            },
            "press_wire": {
                "allowed_document_hosts": ["www.prnewswire.com"],
                "feed_url": (
                    "https://www.prnewswire.com/rss/"
                    "news-releases-list.rss"
                ),
                "kind": "rss",
                "provider": "prnewswire",
                "title_all": [
                    "Garmin",
                    "Second Quarter",
                    "2026",
                    "Results",
                ],
                "title_none": ["schedules"],
            },
        },
    )


def cbre_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = _sec_rule(
        ticker="CBRE",
        cik=CBRE_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T06:55:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        strike=Decimal("1.32"),
        market_slug=(
            "cbre-quarterly-earnings-gaap-eps-07-29-2026-1pt32"
        ),
        condition_id=CBRE_Q2_2026_CONDITION_ID,
        metric_selection="headline_gaap_diluted_eps",
    )
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": ["ir.cbre.com"],
                "feed_url": "https://ir.cbre.com/press-releases/rss",
                "kind": "rss",
                "provider": "company_ir",
                "title_all": [
                    "CBRE",
                    "Reports",
                    "Financial Results",
                    "2026",
                ],
                "title_none": ["conference call"],
            }
        },
    )


def pag_q2_2026_shadow_rule() -> EarningsMarketRule:
    rule = _sec_rule(
        ticker="PAG",
        cik=PENSKE_AUTOMOTIVE_CIK,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T08:00:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        strike=Decimal("3.39"),
        market_slug=(
            "pag-quarterly-earnings-gaap-eps-07-29-2026-3pt39"
        ),
        condition_id=PENSKE_AUTOMOTIVE_Q2_2026_CONDITION_ID,
        metric_selection="reported_gaap_diluted_eps",
    )
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "press_wire": {
                "allowed_document_hosts": ["www.prnewswire.com"],
                "feed_url": (
                    "https://www.prnewswire.com/rss/"
                    "news-releases-list.rss"
                ),
                "kind": "rss",
                "provider": "prnewswire",
                "title_all": [
                    "Penske Automotive Group",
                    "Reports",
                    "Quarter",
                    "Results",
                ],
                "title_none": ["schedules"],
            }
        },
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
    rule = _sec_rule(
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
    title_all = [
        "Meta Reports",
        "Second Quarter",
        "2026",
        "Results",
    ]
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": ["investor.atmeta.com"],
                "feed_url": (
                    "https://investor.atmeta.com/"
                    "rss/pressrelease.aspx"
                ),
                "kind": "rss",
                "provider": "company_ir",
                "title_all": title_all,
                "title_none": ["to announce"],
            },
            "press_wire": {
                "allowed_document_hosts": ["www.prnewswire.com"],
                "feed_url": (
                    "https://www.prnewswire.com/rss/"
                    "news-releases-list.rss"
                ),
                "kind": "rss",
                "provider": "prnewswire",
                "title_all": title_all,
                "title_none": ["to announce"],
            },
        },
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
