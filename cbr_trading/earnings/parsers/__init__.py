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
from cbr_trading.earnings.parsers.navitas import (
    NavitasEpsParser,
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.nxp import (
    NxpNonGaapEpsParser,
    nxpi_q2_2026_shadow_rule,
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
        "NVTS": NavitasEpsParser(),
        "NXPI": NxpNonGaapEpsParser(),
        "WWD": WoodwardGaapEpsParser(),
    }


def checked_in_shadow_rules() -> tuple[EarningsMarketRule, ...]:
    return (
        ba_q2_2026_shadow_rule(),
        csgp_q2_2026_shadow_rule(),
        czr_q2_2026_shadow_rule(),
        nvts_q2_2026_shadow_rule(),
        nxpi_q2_2026_shadow_rule(),
        wwd_q3_2026_shadow_rule(),
        bbby_q2_2026_shadow_rule(),
    )

__all__ = [
    "BedBathBeyondNonGaapEpsParser",
    "BoeingCoreEpsParser",
    "CaesarsGaapEpsParser",
    "CostarGaapEpsParser",
    "NavitasEpsParser",
    "NxpNonGaapEpsParser",
    "WoodwardGaapEpsParser",
    "ba_q2_2026_shadow_rule",
    "bbby_q2_2026_shadow_rule",
    "checked_in_shadow_rules",
    "csgp_q2_2026_shadow_rule",
    "czr_q2_2026_shadow_rule",
    "earnings_parser_registry",
    "nvts_q2_2026_shadow_rule",
    "nxpi_q2_2026_shadow_rule",
    "wwd_q3_2026_shadow_rule",
]
