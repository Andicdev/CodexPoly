from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.fed.contracts import (
    FedDecisionSpec,
    FedMarketBinding,
    FedRateBucket,
)


FED_JULY_2026_DECISION_ID = "fed:fomc:2026-07-29"
FED_JULY_2026_EVENT_SLUG = "fed-decision-in-july-181"
FED_JULY_2026_EVENT_URL = (
    "https://polymarket.com/event/fed-decision-in-july-181"
)


def fed_july_2026_decision_spec() -> FedDecisionSpec:
    return FedDecisionSpec(
        decision_id=FED_JULY_2026_DECISION_ID,
        release_at=datetime(
            2026,
            7,
            29,
            18,
            tzinfo=timezone.utc,
        ),
        previous_lower=Decimal("3.50"),
        previous_upper=Decimal("3.75"),
        board_statement_url=(
            "https://www.federalreserve.gov/newsevents/pressreleases/"
            "monetary20260729a.htm"
        ),
        board_implementation_url=(
            "https://www.federalreserve.gov/newsevents/pressreleases/"
            "monetary20260729a1.htm"
        ),
        new_york_fed_pdf_url=(
            "https://www.newyorkfed.org/medialibrary/media/markets/"
            "fomc-statement-20260729.pdf"
        ),
        monetary_policy_rss_url=(
            "https://www.federalreserve.gov/feeds/press_monetary.xml"
        ),
    )


def fed_july_2026_market_bindings() -> tuple[FedMarketBinding, ...]:
    rows = (
        (
            "fed-jul29-no-change",
            FedRateBucket.NO_CHANGE,
            "==",
            "0",
            (
                "will-there-be-no-change-in-fed-interest-rates-"
                "after-the-july-2026-meeting"
            ),
            (
                "0x8bf1c1536ecb1c08fe13c6b71e8ab1f58bf3461c4cb79f5f"
                "1679f869a06aef86"
            ),
        ),
        (
            "fed-jul29-increase-25",
            FedRateBucket.INCREASE_25,
            "==",
            "25",
            (
                "will-the-fed-increase-interest-rates-by-25-bps-"
                "after-the-july-2026-meeting"
            ),
            (
                "0xb5c0abeecb5502e6e8d83155c27819174d8317af3c425c3af"
                "c5a8c45257a3793"
            ),
        ),
        (
            "fed-jul29-increase-50-plus",
            FedRateBucket.INCREASE_50_PLUS,
            ">=",
            "50",
            (
                "will-the-fed-increase-interest-rates-by-50-bps-"
                "after-the-july-2026-meeting"
            ),
            (
                "0x2a28cc33492516116690a20d290f9922acbe0ed367ff52a608"
                "2154474c7f2971"
            ),
        ),
        (
            "fed-jul29-decrease-25",
            FedRateBucket.DECREASE_25,
            "==",
            "-25",
            (
                "will-the-fed-decrease-interest-rates-by-25-bps-"
                "after-the-july-2026-meeting"
            ),
            (
                "0x4ede078cae84a5877ac32d7fb48811e5c23549a1904b7df06"
                "ff7935c6d79d831"
            ),
        ),
        (
            "fed-jul29-decrease-50-plus",
            FedRateBucket.DECREASE_50_PLUS,
            "<=",
            "-50",
            (
                "will-the-fed-decrease-interest-rates-by-50-bps-"
                "after-the-july-2026-meeting"
            ),
            (
                "0x3d675f1c88099a57c12abca632cf926be1bf430125168321de"
                "06234e9930fe1a"
            ),
        ),
    )
    return tuple(
        FedMarketBinding(
            rule_key=rule_key,
            scope_id=(
                f"{FED_JULY_2026_DECISION_ID}:{bucket.value}"
            ),
            bucket=bucket,
            comparison_op=comparison_op,
            strike_bps=Decimal(strike),
            market_slug=market_slug,
            condition_id=condition_id,
            source_reference=(
                f"{FED_JULY_2026_EVENT_URL}/{market_slug}"
            ),
        )
        for (
            rule_key,
            bucket,
            comparison_op,
            strike,
            market_slug,
            condition_id,
        ) in rows
    )
