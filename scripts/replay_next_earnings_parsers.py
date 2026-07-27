from __future__ import annotations

import argparse
import time
from dataclasses import replace
from datetime import date, datetime, timezone
from urllib.request import Request, urlopen

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    SourceAuthority,
    earnings_scope_id,
)
from cbr_trading.earnings.parsers.boeing import (
    BOEING_CIK,
    BoeingCoreEpsParser,
    ba_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.caesars import (
    CAESARS_CIK,
    CaesarsGaapEpsParser,
    czr_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.costar import (
    COSTAR_CIK,
    CostarGaapEpsParser,
    csgp_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.royal_caribbean import (
    ROYAL_CARIBBEAN_CIK,
    RoyalCaribbeanAdjustedEpsParser,
    rcl_q2_2026_shadow_rule,
)
from cbr_trading.secret_guard import redact_exception


_REPLAYS = {
    "BA": (
        BoeingCoreEpsParser(),
        replace(
            ba_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("BA", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        BOEING_CIK,
        (
            "https://investors.boeing.com/investors/news/"
            "press-release-details/2026/"
            "Boeing-Reports-First-Quarter-Results/default.aspx"
        ),
        "-0.20",
    ),
    "CZR": (
        CaesarsGaapEpsParser(),
        replace(
            czr_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("CZR", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        CAESARS_CIK,
        (
            "https://investor.caesars.com/news-releases/"
            "news-release-details/"
            "caesars-entertainment-inc-reports-first-quarter-"
            "2026-results"
        ),
        "-0.48",
    ),
    "CSGP": (
        CostarGaapEpsParser(),
        replace(
            csgp_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("CSGP", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        COSTAR_CIK,
        "https://investors.costargroup.com/node/16776/html",
        "0.01",
    ),
    "RCL": (
        RoyalCaribbeanAdjustedEpsParser(),
        replace(
            rcl_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("RCL", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        ROYAL_CARIBBEAN_CIK,
        (
            "https://www.rclinvestor.com/press-releases/"
            "release/?id=1832"
        ),
        "3.60",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ticker",
        choices=tuple(_REPLAYS),
        action="append",
        dest="tickers",
    )
    parser.add_argument(
        "--user-agent",
        default="CodexPoly parser replay",
    )
    args = parser.parse_args()
    tickers = tuple(args.tickers or _REPLAYS)
    detected_at = datetime.now(timezone.utc)

    for ticker in tickers:
        company_parser, rule, cik, url, expected = _REPLAYS[ticker]
        try:
            document = _fetch(url, user_agent=args.user_agent)
        except Exception as exc:
            print(
                f"ticker={ticker} status=fetch_error "
                f"detail={redact_exception(exc)} ok=false"
            )
            return 1
        source = EarningsDocumentCandidate(
            scope_id=rule.scope_id,
            provider=EarningsProvider.COMPANY_IR,
            provider_event_id=f"historical-replay:{ticker}:2026Q1",
            ticker=ticker,
            cik=cik,
            form_type="8-K",
            items=("Item 2.02", "Item 9.01"),
            document_type="EX-99.1",
            source_url=url,
            filing_url=url,
            filed_at=detected_at,
            received_at=detected_at,
            authority=SourceAuthority.OFFICIAL_COMPANY,
            transport_fingerprint="historical-replay",
        )
        result = company_parser.parse(
            document,
            source=source,
            rule=rule,
            detected_at=detected_at,
        )
        value = (
            str(result.candidate.value)
            if result.candidate is not None
            else None
        )
        ok = result.status.value == "accepted" and value == expected
        print(
            f"ticker={ticker} status={result.status.value} "
            f"reason={result.reason} value={value} expected={expected} "
            f"ok={str(ok).lower()}"
        )
        if not ok:
            return 1
    return 0


def _fetch(url: str, *, user_agent: str) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": user_agent,
        },
        method="GET",
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return response.read(8 * 1024 * 1024 + 1)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
