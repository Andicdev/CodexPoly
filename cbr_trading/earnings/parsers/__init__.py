"""Company-specific earnings document parsers."""

from cbr_trading.earnings.contracts import EarningsMarketRule
from cbr_trading.earnings.parsers.bed_bath_beyond import (
    BedBathBeyondNonGaapEpsParser,
    bbby_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.navitas import (
    NavitasEpsParser,
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.woodward import (
    WoodwardGaapEpsParser,
    wwd_q3_2026_shadow_rule,
)


def earnings_parser_registry() -> dict[str, object]:
    return {
        "BBBY": BedBathBeyondNonGaapEpsParser(),
        "NVTS": NavitasEpsParser(),
        "WWD": WoodwardGaapEpsParser(),
    }


def checked_in_shadow_rules() -> tuple[EarningsMarketRule, ...]:
    return (
        nvts_q2_2026_shadow_rule(),
        wwd_q3_2026_shadow_rule(),
        bbby_q2_2026_shadow_rule(),
    )

__all__ = [
    "BedBathBeyondNonGaapEpsParser",
    "NavitasEpsParser",
    "WoodwardGaapEpsParser",
    "bbby_q2_2026_shadow_rule",
    "checked_in_shadow_rules",
    "earnings_parser_registry",
    "nvts_q2_2026_shadow_rule",
    "wwd_q3_2026_shadow_rule",
]
