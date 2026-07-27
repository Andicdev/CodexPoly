"""Company-specific earnings document parsers."""

from cbr_trading.earnings.contracts import EarningsMarketRule
from cbr_trading.earnings.parsers.bed_bath_beyond import (
    BedBathBeyondNonGaapEpsParser,
    bbby_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.boeing import (
    BoeingCoreEpsParser,
    ba_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.caesars import (
    CaesarsGaapEpsParser,
    czr_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.costar import (
    CostarGaapEpsParser,
    csgp_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.july_28_sec import (
    CocaColaComparableEpsParser,
    FordAdjustedDilutedEpsParser,
    HiltonAdjustedDilutedEpsParser,
    InvescoAdjustedDilutedEpsParser,
    JetBlueAdjustedDilutedEpsParser,
    PayPalNonGaapEpsParser,
    SpGlobalAdjustedDilutedEpsParser,
    StarbucksGaapEpsParser,
    UpsAdjustedDilutedEpsParser,
    VisaNonGaapEpsParser,
    ford_q2_2026_shadow_rule,
    hlt_q2_2026_shadow_rule,
    ivz_q2_2026_shadow_rule,
    jblu_q2_2026_shadow_rule,
    ko_q2_2026_shadow_rule,
    pypl_q2_2026_shadow_rule,
    sbux_q3_2026_shadow_rule,
    spgi_q2_2026_shadow_rule,
    ups_q2_2026_shadow_rule,
    visa_q3_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.navitas import (
    NavitasEpsParser,
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.nxp import (
    NxpNonGaapEpsParser,
    nxpi_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.royal_caribbean import (
    RoyalCaribbeanAdjustedEpsParser,
    rcl_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.woodward import (
    WoodwardGaapEpsParser,
    wwd_q3_2026_shadow_rule,
)


def earnings_parser_registry() -> dict[str, object]:
    return {
        "BA": BoeingCoreEpsParser(),
        "BBBY": BedBathBeyondNonGaapEpsParser(),
        "CSGP": CostarGaapEpsParser(),
        "CZR": CaesarsGaapEpsParser(),
        "F": FordAdjustedDilutedEpsParser(),
        "HLT": HiltonAdjustedDilutedEpsParser(),
        "IVZ": InvescoAdjustedDilutedEpsParser(),
        "JBLU": JetBlueAdjustedDilutedEpsParser(),
        "KO": CocaColaComparableEpsParser(),
        "NVTS": NavitasEpsParser(),
        "NXPI": NxpNonGaapEpsParser(),
        "PYPL": PayPalNonGaapEpsParser(),
        "RCL": RoyalCaribbeanAdjustedEpsParser(),
        "SBUX": StarbucksGaapEpsParser(),
        "SPGI": SpGlobalAdjustedDilutedEpsParser(),
        "UPS": UpsAdjustedDilutedEpsParser(),
        "V": VisaNonGaapEpsParser(),
        "WWD": WoodwardGaapEpsParser(),
    }


def checked_in_shadow_rules() -> tuple[EarningsMarketRule, ...]:
    return (
        ba_q2_2026_shadow_rule(),
        csgp_q2_2026_shadow_rule(),
        czr_q2_2026_shadow_rule(),
        ford_q2_2026_shadow_rule(),
        hlt_q2_2026_shadow_rule(),
        ivz_q2_2026_shadow_rule(),
        jblu_q2_2026_shadow_rule(),
        ko_q2_2026_shadow_rule(),
        nvts_q2_2026_shadow_rule(),
        nxpi_q2_2026_shadow_rule(),
        pypl_q2_2026_shadow_rule(),
        rcl_q2_2026_shadow_rule(),
        sbux_q3_2026_shadow_rule(),
        spgi_q2_2026_shadow_rule(),
        ups_q2_2026_shadow_rule(),
        visa_q3_2026_shadow_rule(),
        wwd_q3_2026_shadow_rule(),
        bbby_q2_2026_shadow_rule(),
    )

__all__ = [
    "BedBathBeyondNonGaapEpsParser",
    "BoeingCoreEpsParser",
    "CaesarsGaapEpsParser",
    "CostarGaapEpsParser",
    "CocaColaComparableEpsParser",
    "FordAdjustedDilutedEpsParser",
    "HiltonAdjustedDilutedEpsParser",
    "InvescoAdjustedDilutedEpsParser",
    "JetBlueAdjustedDilutedEpsParser",
    "NavitasEpsParser",
    "NxpNonGaapEpsParser",
    "PayPalNonGaapEpsParser",
    "RoyalCaribbeanAdjustedEpsParser",
    "SpGlobalAdjustedDilutedEpsParser",
    "StarbucksGaapEpsParser",
    "UpsAdjustedDilutedEpsParser",
    "VisaNonGaapEpsParser",
    "WoodwardGaapEpsParser",
    "ba_q2_2026_shadow_rule",
    "bbby_q2_2026_shadow_rule",
    "checked_in_shadow_rules",
    "csgp_q2_2026_shadow_rule",
    "czr_q2_2026_shadow_rule",
    "earnings_parser_registry",
    "ford_q2_2026_shadow_rule",
    "hlt_q2_2026_shadow_rule",
    "ivz_q2_2026_shadow_rule",
    "jblu_q2_2026_shadow_rule",
    "ko_q2_2026_shadow_rule",
    "nvts_q2_2026_shadow_rule",
    "nxpi_q2_2026_shadow_rule",
    "pypl_q2_2026_shadow_rule",
    "rcl_q2_2026_shadow_rule",
    "sbux_q3_2026_shadow_rule",
    "spgi_q2_2026_shadow_rule",
    "ups_q2_2026_shadow_rule",
    "visa_q3_2026_shadow_rule",
    "wwd_q3_2026_shadow_rule",
]
