"""Company-specific earnings document parsers."""

from cbr_trading.earnings.parsers.navitas import (
    NavitasEpsParser,
    nvts_q2_2026_shadow_rule,
)

__all__ = [
    "NavitasEpsParser",
    "nvts_q2_2026_shadow_rule",
]
