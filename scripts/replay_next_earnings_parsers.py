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
from cbr_trading.earnings.parsers.amazon import (
    AMAZON_CIK,
    AmazonGaapDilutedEpsParser,
    amzn_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.apple import (
    APPLE_CIK,
    AppleGaapDilutedEpsParser,
    aapl_q3_2026_shadow_rule,
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
from cbr_trading.earnings.parsers.dolby import (
    DOLBY_CIK,
    DolbyNonGaapDilutedEpsParser,
    dlb_q3_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.july_28_sec import (
    COCA_COLA_CIK,
    FORD_CIK,
    HILTON_CIK,
    INVESCO_CIK,
    JETBLUE_CIK,
    PAYPAL_CIK,
    SP_GLOBAL_CIK,
    STARBUCKS_CIK,
    UPS_CIK,
    VISA_CIK,
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
from cbr_trading.earnings.parsers.july_30_sec import (
    CIGNA_GROUP_CIK,
    INTERCONTINENTAL_EXCHANGE_CIK,
    MASTERCARD_CIK,
    YUM_BRANDS_CIK,
    CignaAdjustedIncomePerShareParser,
    IceAdjustedDilutedEpsParser,
    MastercardAdjustedDilutedEpsParser,
    YumEpsExcludingSpecialItemsParser,
    ci_q2_2026_shadow_rule,
    ice_q2_2026_shadow_rule,
    mastercard_q2_2026_shadow_rule,
    yum_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.royal_caribbean import (
    ROYAL_CARIBBEAN_CIK,
    RoyalCaribbeanAdjustedEpsParser,
    rcl_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.reddit import (
    REDDIT_CIK,
    RedditGaapDilutedEpsParser,
    rddt_q2_2026_shadow_rule,
)
from cbr_trading.secret_guard import redact_exception


_REPLAYS = {
    "AAPL": (
        AppleGaapDilutedEpsParser(),
        replace(
            aapl_q3_2026_shadow_rule(),
            scope_id=earnings_scope_id("AAPL", 2025, 3),
            fiscal_year=2025,
            fiscal_quarter=3,
            period_end=date(2025, 6, 28),
        ),
        APPLE_CIK,
        (
            "https://www.apple.com/newsroom/2025/07/"
            "apple-reports-third-quarter-results/"
        ),
        "1.57",
    ),
    "AMZN": (
        AmazonGaapDilutedEpsParser(),
        replace(
            amzn_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("AMZN", 2025, 2),
            fiscal_year=2025,
            fiscal_quarter=2,
            period_end=date(2025, 6, 30),
        ),
        AMAZON_CIK,
        (
            "https://ir.aboutamazon.com/news-release/"
            "news-release-details/2025/"
            "Amazon-com-Announces-Second-Quarter-Results/"
            "default.aspx"
        ),
        "1.68",
    ),
    "CI": (
        CignaAdjustedIncomePerShareParser(),
        replace(
            ci_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("CI", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        CIGNA_GROUP_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/1739940/"
            "000114036126017971/ef20071317_ex99-1.htm"
        ),
        "7.79",
    ),
    "ICE": (
        IceAdjustedDilutedEpsParser(),
        replace(
            ice_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("ICE", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        INTERCONTINENTAL_EXCHANGE_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/1571949/"
            "000110465926052145/tm2612824d1_ex99-1.htm"
        ),
        "2.35",
    ),
    "YUM": (
        YumEpsExcludingSpecialItemsParser(),
        replace(
            yum_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("YUM", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        YUM_BRANDS_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/1041061/"
            "000104106126000108/a8kex9914292026.htm"
        ),
        "1.50",
    ),
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
    "DLB": (
        DolbyNonGaapDilutedEpsParser(),
        replace(
            dlb_q3_2026_shadow_rule(),
            scope_id=earnings_scope_id("DLB", 2025, 3),
            fiscal_year=2025,
            fiscal_quarter=3,
            period_end=date(2025, 6, 27),
        ),
        DOLBY_CIK,
        (
            "https://investor.dolby.com/news-events/"
            "financial-news/news-details/2025/"
            "Dolby-Laboratories-Reports-Third-Quarter-"
            "2025-Financial-Results/"
        ),
        "0.78",
    ),
    "F": (
        FordAdjustedDilutedEpsParser(),
        replace(
            ford_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("F", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        FORD_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/37996/"
            "000003799626000084/exhibit99toapril292026fo.htm"
        ),
        "0.14",
    ),
    "HLT": (
        HiltonAdjustedDilutedEpsParser(),
        replace(
            hlt_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("HLT", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        HILTON_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/1585689/"
            "000158568926000031/q12026earningsrelease.htm"
        ),
        "2.01",
    ),
    "IVZ": (
        InvescoAdjustedDilutedEpsParser(),
        replace(
            ivz_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("IVZ", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        INVESCO_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/914208/"
            "000091420826000102/ivzpressrelease1q2026.htm"
        ),
        "0.57",
    ),
    "JBLU": (
        JetBlueAdjustedDilutedEpsParser(),
        replace(
            jblu_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("JBLU", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        JETBLUE_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/1158463/"
            "000115846326000060/ex991-earningsreleaseq12026.htm"
        ),
        "-0.87",
    ),
    "KO": (
        CocaColaComparableEpsParser(),
        replace(
            ko_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("KO", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 4, 3),
        ),
        COCA_COLA_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/21344/"
            "000162828026027723/a2026q1earningsreleaseex-9.htm"
        ),
        "0.86",
    ),
    "MA": (
        MastercardAdjustedDilutedEpsParser(),
        replace(
            mastercard_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("MA", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        MASTERCARD_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/1141391/"
            "000114139126000029/"
            "ma03312026-exx991xearnings.htm"
        ),
        "4.60",
    ),
    "PYPL": (
        PayPalNonGaapEpsParser(),
        replace(
            pypl_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("PYPL", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        PAYPAL_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/1633917/"
            "000163391726000065/pypl1q-26earningsrelease.htm"
        ),
        "1.34",
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
    "RDDT": (
        RedditGaapDilutedEpsParser(),
        replace(
            rddt_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("RDDT", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        REDDIT_CIK,
        (
            "https://investor.redditinc.com/news-events/"
            "news-releases/news-details/2026/"
            "Reddit-Reports-First-Quarter-2026-Results/"
            "default.aspx"
        ),
        "1.01",
    ),
    "SBUX": (
        StarbucksGaapEpsParser(),
        replace(
            sbux_q3_2026_shadow_rule(),
            scope_id=earnings_scope_id("SBUX", 2026, 2),
            fiscal_quarter=2,
            period_end=date(2026, 3, 29),
        ),
        STARBUCKS_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/829224/"
            "000082922426000078/sbux-03292026xearningsrele.htm"
        ),
        "0.45",
    ),
    "SPGI": (
        SpGlobalAdjustedDilutedEpsParser(),
        replace(
            spgi_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("SPGI", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        SP_GLOBAL_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/64040/"
            "000006404026000019/spgi1q2026-earningsrelease.htm"
        ),
        "4.97",
    ),
    "UPS": (
        UpsAdjustedDilutedEpsParser(),
        replace(
            ups_q2_2026_shadow_rule(),
            scope_id=earnings_scope_id("UPS", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        ),
        UPS_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/1090727/"
            "000162828026027717/exhibit991-earningspressre.htm"
        ),
        "1.07",
    ),
    "V": (
        VisaNonGaapEpsParser(),
        replace(
            visa_q3_2026_shadow_rule(),
            scope_id=earnings_scope_id("V", 2026, 2),
            fiscal_quarter=2,
            period_end=date(2026, 3, 31),
        ),
        VISA_CIK,
        (
            "https://www.sec.gov/Archives/edgar/data/1403161/"
            "000140316126000077/q22026earningsrelease.htm"
        ),
        "3.31",
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
            provider=(
                EarningsProvider.SEC
                if "sec.gov" in url
                else EarningsProvider.COMPANY_IR
            ),
            provider_event_id=(
                f"historical-replay:{ticker}:"
                f"{rule.fiscal_year}Q{rule.fiscal_quarter}"
            ),
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
