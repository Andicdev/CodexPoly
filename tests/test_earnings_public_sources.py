from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from unittest.mock import patch

from cbr_trading.earnings.contracts import (
    EarningsProvider,
    EarningsTransport,
)
from cbr_trading.earnings.parsers.boeing import (
    ba_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.july_28_sec import (
    ford_q2_2026_shadow_rule,
    hlt_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.july_29_sec import (
    arcc_q2_2026_shadow_rule,
    cbre_q2_2026_shadow_rule,
    ea_q1_2027_shadow_rule,
    grmn_q2_2026_shadow_rule,
    hood_q2_2026_shadow_rule,
    hum_q2_2026_shadow_rule,
    iart_q2_2026_shadow_rule,
    meta_q2_2026_shadow_rule,
    msft_q4_2026_shadow_rule,
    qcom_q3_2026_shadow_rule,
    pag_q2_2026_shadow_rule,
    pg_q4_2026_shadow_rule,
    sofi_q2_2026_shadow_rule,
    way_q2_2026_shadow_rule,
    wing_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.royal_caribbean import (
    rcl_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.woodward import (
    wwd_q3_2026_shadow_rule,
)
from cbr_trading.earnings.public_sources import (
    PublicReleaseDocumentFetcher,
    PublicReleaseFeedClient,
    PublicReleaseSourceError,
    public_release_watches_from_rules,
)


_RECEIVED_AT = datetime(
    2026,
    7,
    27,
    20,
    0,
    1,
    tzinfo=timezone.utc,
)
_IR_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>
        Navitas Semiconductor Announces Second Quarter 2026
        Financial Results
      </title>
      <link>https://ir.navitassemi.com/news-releases/q2-results</link>
      <pubDate>Mon, 27 Jul 2026 16:00:00 -0400</pubDate>
      <guid isPermaLink="false">nvts-ir-q2-2026</guid>
    </item>
  </channel>
</rss>
"""
_GLOBE_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel xmlns:dc="http://purl.org/dc/elements/1.1/">
    <item>
      <guid isPermaLink="true">
        https://www.globenewswire.com/news-release/nvts-q2.html
      </guid>
      <link>https://www.globenewswire.com/news-release/nvts-q2.html</link>
      <title>
        Navitas Semiconductor Announces Second Quarter 2026
        Financial Results
      </title>
      <pubDate>Mon, 27 Jul 2026 20:00:02 GMT</pubDate>
      <dc:identifier>3333999</dc:identifier>
      <dc:contributor>Navitas Semiconductor Corporation</dc:contributor>
    </item>
    <item>
      <link>https://www.globenewswire.com/news-release/schedule.html</link>
      <title>
        Navitas Semiconductor to Report Second Quarter 2026
        Financial Results
      </title>
      <pubDate>Mon, 06 Jul 2026 12:00:00 GMT</pubDate>
      <dc:identifier>3332000</dc:identifier>
    </item>
  </channel>
</rss>
"""
_WWD_WORDPRESS_LISTING = b"""[
  {
    "id": 24582,
    "date_gmt": "2026-07-21T11:30:00",
    "modified_gmt": "2026-07-21T11:30:00",
    "link": "https://www.woodward.com/press-release/other-news/",
    "title": {"rendered": "Woodward Inaugurates Expanded Production"}
  },
  {
    "id": 25000,
    "date_gmt": "2026-07-29T20:00:03",
    "modified_gmt": "2026-07-29T20:00:03",
    "link": "https://www.woodward.com/press-release/woodward-q3-2026/",
    "title": {
      "rendered": "Woodward Reports Third Quarter Fiscal Year 2026 Results"
    }
  }
]"""
_RCL_HTML_LISTING = b"""
<html>
  <body>
    <div class="release">
      <p class="date">July 28, 2026 6:30 am</p>
      <p>
        <a
          href="https://www.rclinvestor.com/press-releases/release/?id=1842"
          title="ROYAL CARIBBEAN GROUP REPORTS SECOND QUARTER RESULTS"
        >
          ROYAL CARIBBEAN GROUP REPORTS SECOND QUARTER RESULTS
        </a>
      </p>
    </div>
    <div class="release">
      <p class="date">July 8, 2026 4:30 pm</p>
      <p>
        <a
          href="https://www.rclinvestor.com/press-releases/release/?id=1841"
          title="ROYAL CARIBBEAN GROUP TO HOLD CONFERENCE CALL ON SECOND QUARTER 2026 EARNINGS"
        >
          ROYAL CARIBBEAN GROUP TO HOLD CONFERENCE CALL ON SECOND
          QUARTER 2026 EARNINGS
        </a>
      </p>
    </div>
  </body>
</html>
"""
_BA_PR_NEWSWIRE_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <guid isPermaLink="true">
        https://www.prnewswire.com/news-releases/boeing-reports-second-quarter-results-302516005.html
      </guid>
      <link>https://www.prnewswire.com/news-releases/boeing-reports-second-quarter-results-302516005.html</link>
      <title>Boeing Reports Second Quarter Results</title>
      <pubDate>Tue, 28 Jul 2026 11:30:00 GMT</pubDate>
    </item>
    <item>
      <link>https://www.prnewswire.com/news-releases/boeing-announces-second-quarter-deliveries-302499301.html</link>
      <title>Boeing Announces Second Quarter Deliveries</title>
      <pubDate>Tue, 08 Jul 2025 11:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
_HLT_STORIES_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <guid isPermaLink="true">
        https://stories.hilton.com/releases/hilton-reports-2026-second-quarter-results
      </guid>
      <link>https://stories.hilton.com/releases/hilton-reports-2026-second-quarter-results</link>
      <title>Hilton Reports 2026 Second Quarter Results</title>
      <pubDate>Tue, 28 Jul 2026 10:00:03 GMT</pubDate>
    </item>
    <item>
      <link>https://stories.hilton.com/releases/hilton-releases-second-quarter-2026-earnings-date</link>
      <title>Hilton Announces Second Quarter 2026 Earnings Release Date</title>
      <pubDate>Mon, 29 Jun 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
_BUSINESS_WIRE_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <guid isPermaLink="true">
        https://www.businesswire.com/news/home/arcc-q2-2026
      </guid>
      <link>https://www.businesswire.com/news/home/arcc-q2-2026</link>
      <title>
        Ares Capital Corporation Announces June 30, 2026 Financial
        Results and Declares Third Quarter 2026 Dividend
      </title>
      <pubDate>Wed, 29 Jul 2026 11:00:01 GMT</pubDate>
    </item>
    <item>
      <guid isPermaLink="true">
        https://www.businesswire.com/news/home/sofi-q2-2026
      </guid>
      <link>https://www.businesswire.com/news/home/sofi-q2-2026</link>
      <title>SoFi Reports Second Quarter 2026 Results</title>
      <pubDate>Wed, 29 Jul 2026 11:00:02 GMT</pubDate>
    </item>
    <item>
      <guid isPermaLink="true">
        https://www.businesswire.com/news/home/pg-q4-2026
      </guid>
      <link>https://www.businesswire.com/news/home/pg-q4-2026</link>
      <title>
        P&amp;G Announces Fourth Quarter and Fiscal Year 2026 Results
      </title>
      <pubDate>Wed, 29 Jul 2026 11:00:03 GMT</pubDate>
    </item>
    <item>
      <guid isPermaLink="true">
        https://www.businesswire.com/news/home/sofi-schedule
      </guid>
      <link>https://www.businesswire.com/news/home/sofi-schedule</link>
      <title>SoFi Schedules Second Quarter 2026 Results Call</title>
      <pubDate>Wed, 01 Jul 2026 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""
_META_IR_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <guid isPermaLink="true">
        https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-Second-Quarter-2026-Results/default.aspx
      </guid>
      <link>https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-Second-Quarter-2026-Results/default.aspx</link>
      <title>Meta Reports Second Quarter 2026 Results</title>
      <pubDate>Wed, 29 Jul 2026 16:01:00 -0400</pubDate>
    </item>
    <item>
      <link>https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-to-Announce-Second-Quarter-2026-Results/default.aspx</link>
      <title>Meta to Announce Second Quarter 2026 Results</title>
      <pubDate>Tue, 14 Jul 2026 16:05:00 -0400</pubDate>
    </item>
  </channel>
</rss>
"""
_MSFT_IR_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <item>
      <guid isPermaLink="true">
        https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q4/press-release-webcast
      </guid>
      <link>https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q4/press-release-webcast</link>
      <title>
        Microsoft Cloud and AI strength fuels fourth quarter results
      </title>
      <pubDate>Wed, 29 Jul 2026 20:10:38 +0000</pubDate>
    </item>
    <item>
      <link>https://news.microsoft.com/source/2026/07/08/microsoft-announces-quarterly-earnings-release-date-68/</link>
      <title>Microsoft announces quarterly earnings release date</title>
      <pubDate>Wed, 08 Jul 2026 20:05:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


class _Response:
    def __init__(
        self,
        content: bytes,
        *,
        url: str,
        status: int = 200,
        content_type: str = "application/rss+xml",
        extra_headers: dict[str, str] | None = None,
    ):
        self._content = content
        self._url = url
        self.status = status
        self.read_sizes: list[int] = []
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        for name, value in (extra_headers or {}).items():
            self.headers[name] = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._content[:size]

    def geturl(self) -> str:
        return self._url


class EarningsPublicSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.watches = public_release_watches_from_rules(
            (nvts_q2_2026_shadow_rule(),)
        )
        self.by_provider = {
            watch.provider: watch
            for watch in self.watches
        }

    def test_nvts_rule_builds_ir_and_globenewswire_watches(self) -> None:
        self.assertEqual(
            set(self.by_provider),
            {
                EarningsProvider.COMPANY_IR,
                EarningsProvider.GLOBE_NEWSWIRE,
            },
        )
        self.assertTrue(
            self.by_provider[
                EarningsProvider.COMPANY_IR
            ].feed_url.startswith(
                "https://navitassemi.gcs-web.com/"
            )
        )
        self.assertTrue(
            all(watch.kind == "rss" for watch in self.watches)
        )
        self.assertTrue(
            all(
                watch.published_not_before is not None
                for watch in self.watches
            )
        )

    def test_direct_document_probe_routes_ford_pdf(self) -> None:
        watch = public_release_watches_from_rules(
            (ford_q2_2026_shadow_rule(),)
        )[0]
        requests = []

        def opener(request, *, timeout):
            requests.append((request, timeout))
            return _Response(
                b"",
                url=request.full_url,
                content_type="application/pdf",
                extra_headers={
                    "ETag": '"ford-q2-2026"',
                    "Last-Modified": (
                        "Tue, 28 Jul 2026 20:06:18 GMT"
                    ),
                },
            )

        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=2,
            opener=opener,
        ).poll((watch,), received_at=_RECEIVED_AT)

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.document_type, "PDF")
        self.assertEqual(
            candidate.transport,
            EarningsTransport.COMPANY_IR_POLL,
        )
        self.assertEqual(
            candidate.filed_at.isoformat(),
            "2026-07-28T20:06:18+00:00",
        )
        self.assertEqual(requests[0][0].method, "HEAD")
        self.assertEqual(requests[0][1], 2)

    def test_public_pdf_is_converted_to_parser_text(self) -> None:
        watch = public_release_watches_from_rules(
            (ford_q2_2026_shadow_rule(),)
        )[0]
        candidate = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=2,
            opener=lambda request, **_kwargs: _Response(
                b"",
                url=request.full_url,
                content_type="application/pdf",
                extra_headers={
                    "Last-Modified": (
                        "Tue, 28 Jul 2026 20:06:18 GMT"
                    ),
                },
            ),
        ).poll((watch,), received_at=_RECEIVED_AT).candidates[0]
        page = type(
            "_Page",
            (),
            {"extract_text": lambda self: "Adjusted EPS $0.42"},
        )()
        reader = type("_Reader", (), {"pages": [page]})()
        fetcher = PublicReleaseDocumentFetcher(
            watches=(watch,),
            user_agent="CodexPoly test@example.com",
            timeout=3,
            max_bytes=4096,
            opener=lambda request, **_kwargs: _Response(
                b"%PDF-test",
                url=request.full_url,
                content_type="application/pdf",
            ),
        )

        with patch(
            "cbr_trading.earnings.public_sources.PdfReader",
            return_value=reader,
        ):
            fetch_result = fetcher.fetch_with_result(candidate)

        self.assertEqual(
            fetch_result.document,
            b"Adjusted EPS $0.42",
        )
        self.assertEqual(fetch_result.route, "public_pdf_text")

    def test_july_29_premarket_public_source_matrix(self) -> None:
        expected = {
            "WING": {
                EarningsProvider.COMPANY_IR,
                EarningsProvider.PR_NEWSWIRE,
            },
            "ARCC": {EarningsProvider.BUSINESS_WIRE},
            "IART": {
                EarningsProvider.COMPANY_IR,
                EarningsProvider.GLOBE_NEWSWIRE,
            },
            "GRMN": {
                EarningsProvider.COMPANY_IR,
                EarningsProvider.PR_NEWSWIRE,
            },
            "CBRE": {EarningsProvider.COMPANY_IR},
            "PAG": {EarningsProvider.PR_NEWSWIRE},
            "HUM": {EarningsProvider.COMPANY_IR},
            "SOFI": {EarningsProvider.BUSINESS_WIRE},
            "PG": {EarningsProvider.BUSINESS_WIRE},
        }
        rules = (
            wing_q2_2026_shadow_rule(),
            arcc_q2_2026_shadow_rule(),
            iart_q2_2026_shadow_rule(),
            grmn_q2_2026_shadow_rule(),
            cbre_q2_2026_shadow_rule(),
            pag_q2_2026_shadow_rule(),
            hum_q2_2026_shadow_rule(),
            sofi_q2_2026_shadow_rule(),
            pg_q4_2026_shadow_rule(),
        )

        for rule in rules:
            with self.subTest(ticker=rule.ticker):
                providers = {
                    watch.provider
                    for watch in public_release_watches_from_rules((rule,))
                }
                self.assertEqual(providers, expected[rule.ticker])

    def test_ea_postmarket_public_source_matrix(self) -> None:
        providers = {
            watch.provider
            for watch in public_release_watches_from_rules(
                (ea_q1_2027_shadow_rule(),)
            )
        }

        self.assertEqual(
            providers,
            {
                EarningsProvider.COMPANY_IR,
                EarningsProvider.BUSINESS_WIRE,
            },
        )

    def test_hood_postmarket_public_source_matrix(self) -> None:
        providers = {
            watch.provider
            for watch in public_release_watches_from_rules(
                (hood_q2_2026_shadow_rule(),)
            )
        }

        self.assertEqual(
            providers,
            {
                EarningsProvider.COMPANY_IR,
                EarningsProvider.GLOBE_NEWSWIRE,
            },
        )

    def test_way_postmarket_public_source_matrix(self) -> None:
        providers = {
            watch.provider
            for watch in public_release_watches_from_rules(
                (way_q2_2026_shadow_rule(),)
            )
        }

        self.assertEqual(
            providers,
            {
                EarningsProvider.COMPANY_IR,
                EarningsProvider.PR_NEWSWIRE,
            },
        )

    def test_ignores_matching_release_older_than_rule_lookback(
        self,
    ) -> None:
        company_watch = self.by_provider[EarningsProvider.COMPANY_IR]
        stale_feed = _IR_FEED.replace(
            b"Mon, 27 Jul 2026 16:00:00 -0400",
            b"Wed, 01 Jul 2026 16:00:00 -0400",
        )

        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                stale_feed,
                url=request.full_url,
            ),
        ).poll((company_watch,), received_at=_RECEIVED_AT)

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(result.candidates, ())

    def test_routes_woodward_wordpress_candidate(self) -> None:
        watches = public_release_watches_from_rules(
            (wwd_q3_2026_shadow_rule(),)
        )
        by_provider = {
            watch.provider: watch
            for watch in watches
        }
        company_watch = by_provider[EarningsProvider.COMPANY_IR]
        self.assertEqual(company_watch.kind, "wordpress_rest")

        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                _WWD_WORDPRESS_LISTING,
                url=request.full_url,
                content_type="application/json",
            ),
        ).poll((company_watch,), received_at=_RECEIVED_AT)

        self.assertEqual(result.feed_count, 1)
        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(candidate.provider_event_id, "25000")
        self.assertEqual(
            candidate.source_url,
            (
                "https://www.woodward.com/press-release/"
                "woodward-q3-2026/"
            ),
        )
        self.assertEqual(
            candidate.filed_at.isoformat(),
            "2026-07-29T20:00:03+00:00",
        )
        self.assertEqual(
            candidate.metadata["listing_kind"],
            "wordpress_rest",
        )

    def test_routes_rcl_html_listing_candidate(self) -> None:
        watches = public_release_watches_from_rules(
            (rcl_q2_2026_shadow_rule(),)
        )
        by_provider = {
            watch.provider: watch
            for watch in watches
        }
        company_watch = by_provider[EarningsProvider.COMPANY_IR]
        self.assertEqual(company_watch.kind, "html_listing")
        self.assertEqual(
            company_watch.listing_utc_offset_minutes,
            -240,
        )

        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                _RCL_HTML_LISTING,
                url=request.full_url,
                content_type="text/html",
            ),
        ).poll((company_watch,), received_at=_RECEIVED_AT)

        self.assertEqual(result.feed_count, 1)
        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(
            candidate.source_url,
            (
                "https://www.rclinvestor.com/press-releases/"
                "release/?id=1842"
            ),
        )
        self.assertEqual(
            candidate.filed_at.isoformat(),
            "2026-07-28T10:30:00+00:00",
        )
        self.assertEqual(
            candidate.metadata["listing_kind"],
            "html_listing",
        )
        self.assertIn(
            EarningsProvider.PR_NEWSWIRE,
            by_provider,
        )

    def test_routes_only_boeing_results_from_prnewswire(self) -> None:
        watches = public_release_watches_from_rules(
            (ba_q2_2026_shadow_rule(),)
        )
        by_provider = {
            watch.provider: watch
            for watch in watches
        }
        self.assertEqual(
            set(by_provider),
            {
                EarningsProvider.COMPANY_IR,
                EarningsProvider.PR_NEWSWIRE,
            },
        )
        press_wire = by_provider[EarningsProvider.PR_NEWSWIRE]

        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                _BA_PR_NEWSWIRE_FEED,
                url=request.full_url,
            ),
        ).poll((press_wire,), received_at=_RECEIVED_AT)

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(
            candidate.provider,
            EarningsProvider.PR_NEWSWIRE,
        )
        self.assertIn(
            "boeing-reports-second-quarter-results",
            candidate.source_url,
        )
        self.assertNotIn("deliveries", candidate.source_url)

    def test_routes_only_hilton_results_from_official_feed(self) -> None:
        watches = public_release_watches_from_rules(
            (hlt_q2_2026_shadow_rule(),)
        )
        self.assertEqual(len(watches), 1)
        company_watch = watches[0]
        self.assertEqual(
            company_watch.provider,
            EarningsProvider.COMPANY_IR,
        )

        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                _HLT_STORIES_FEED,
                url=request.full_url,
            ),
        ).poll((company_watch,), received_at=_RECEIVED_AT)

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(
            candidate.provider,
            EarningsProvider.COMPANY_IR,
        )
        self.assertIn(
            "hilton-reports-2026-second-quarter-results",
            candidate.source_url,
        )
        self.assertNotIn("earnings-date", candidate.source_url)

    def test_meta_builds_ir_and_prnewswire_watches(self) -> None:
        watches = public_release_watches_from_rules(
            (meta_q2_2026_shadow_rule(),)
        )
        by_provider = {
            watch.provider: watch
            for watch in watches
        }
        self.assertEqual(
            set(by_provider),
            {
                EarningsProvider.COMPANY_IR,
                EarningsProvider.PR_NEWSWIRE,
            },
        )
        self.assertEqual(
            by_provider[EarningsProvider.COMPANY_IR].feed_url,
            "https://investor.atmeta.com/rss/pressrelease.aspx",
        )

    def test_meta_ir_routes_results_and_rejects_announcement(self) -> None:
        company_watch = next(
            watch
            for watch in public_release_watches_from_rules(
                (meta_q2_2026_shadow_rule(),)
            )
            if watch.provider is EarningsProvider.COMPANY_IR
        )
        received_at = datetime(
            2026,
            7,
            29,
            20,
            1,
            3,
            tzinfo=timezone.utc,
        )
        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                _META_IR_FEED,
                url=request.full_url,
            ),
        ).poll((company_watch,), received_at=received_at)

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(
            candidate.provider,
            EarningsProvider.COMPANY_IR,
        )
        self.assertIn(
            "Meta-Reports-Second-Quarter-2026-Results",
            candidate.source_url,
        )
        self.assertNotIn("to-Announce", candidate.source_url)

    def test_microsoft_builds_official_investor_rss_watch(self) -> None:
        watches = public_release_watches_from_rules(
            (msft_q4_2026_shadow_rule(),)
        )
        self.assertEqual(len(watches), 1)
        watch = watches[0]
        self.assertEqual(
            watch.provider,
            EarningsProvider.COMPANY_IR,
        )
        self.assertEqual(
            watch.feed_url,
            (
                "https://news.microsoft.com/source/tag/"
                "investor-relations/feed/"
            ),
        )
        self.assertEqual(
            watch.allowed_document_hosts,
            ("www.microsoft.com",),
        )

    def test_qualcomm_builds_direct_official_earnings_pdf_watch(
        self,
    ) -> None:
        watches = public_release_watches_from_rules(
            (qcom_q3_2026_shadow_rule(),)
        )
        self.assertEqual(len(watches), 1)
        watch = watches[0]
        self.assertEqual(
            watch.provider,
            EarningsProvider.COMPANY_IR,
        )
        self.assertEqual(watch.kind, "direct_document")
        self.assertEqual(
            watch.feed_url,
            (
                "https://s204.q4cdn.com/645488518/files/"
                "doc_financials/2026/q3/"
                "FY2026-3rd-Quarter-Earnings-Release.pdf"
            ),
        )
        self.assertEqual(
            watch.allowed_document_hosts,
            ("s204.q4cdn.com",),
        )

    def test_microsoft_ir_routes_results_and_rejects_announcement(
        self,
    ) -> None:
        watch = public_release_watches_from_rules(
            (msft_q4_2026_shadow_rule(),)
        )[0]
        received_at = datetime(
            2026,
            7,
            29,
            20,
            10,
            40,
            tzinfo=timezone.utc,
        )
        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                _MSFT_IR_FEED,
                url=request.full_url,
            ),
        ).poll((watch,), received_at=received_at)

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(len(result.candidates), 1)
        candidate = result.candidates[0]
        self.assertEqual(
            candidate.provider,
            EarningsProvider.COMPANY_IR,
        )
        self.assertIn(
            "FY-2026-Q4/press-release-webcast",
            candidate.source_url,
        )
        self.assertNotIn("release-date", candidate.source_url)

    def test_businesswire_feed_routes_each_premarket_issuer(self) -> None:
        rules = (
            arcc_q2_2026_shadow_rule(),
            sofi_q2_2026_shadow_rule(),
            pg_q4_2026_shadow_rule(),
        )
        received_at = datetime(
            2026,
            7,
            29,
            11,
            0,
            5,
            tzinfo=timezone.utc,
        )

        for rule in rules:
            with self.subTest(ticker=rule.ticker):
                watches = public_release_watches_from_rules((rule,))
                self.assertEqual(len(watches), 1)
                watch = watches[0]
                self.assertEqual(
                    watch.provider,
                    EarningsProvider.BUSINESS_WIRE,
                )
                result = PublicReleaseFeedClient(
                    user_agent="CodexPoly test@example.com",
                    timeout=3,
                    opener=lambda request, **_kwargs: _Response(
                        _BUSINESS_WIRE_FEED,
                        url=request.full_url,
                    ),
                ).poll((watch,), received_at=received_at)

                self.assertEqual(result.success_count, 1)
                self.assertEqual(result.error_count, 0)
                self.assertEqual(len(result.candidates), 1)
                self.assertIn(
                    rule.ticker.casefold(),
                    result.candidates[0].source_url.casefold(),
                )

    def test_rejects_non_array_wordpress_listing(self) -> None:
        company_watch = next(
            watch
            for watch in public_release_watches_from_rules(
                (wwd_q3_2026_shadow_rule(),)
            )
            if watch.provider is EarningsProvider.COMPANY_IR
        )
        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                b'{"id": 25000}',
                url=request.full_url,
                content_type="application/json",
            ),
        ).poll((company_watch,), received_at=_RECEIVED_AT)

        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.candidates, ())

    def test_routes_one_exact_candidate_from_each_feed(self) -> None:
        feeds = {
            self.by_provider[
                EarningsProvider.COMPANY_IR
            ].feed_url: _IR_FEED,
            self.by_provider[
                EarningsProvider.GLOBE_NEWSWIRE
            ].feed_url: _GLOBE_FEED,
        }
        requests = []

        def opener(request, *, timeout):
            requests.append((request, timeout))
            return _Response(
                feeds[request.full_url],
                url=request.full_url,
                extra_headers={"ETag": '"feed-version"'},
            )

        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=opener,
        ).poll(self.watches, received_at=_RECEIVED_AT)

        self.assertEqual(result.feed_count, 2)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(
            {item.provider for item in result.candidates},
            {
                EarningsProvider.COMPANY_IR,
                EarningsProvider.GLOBE_NEWSWIRE,
            },
        )
        globe = next(
            item
            for item in result.candidates
            if item.provider is EarningsProvider.GLOBE_NEWSWIRE
        )
        self.assertEqual(globe.provider_event_id, "3333999")
        self.assertEqual(globe.received_at, _RECEIVED_AT)
        self.assertNotIn("schedule", globe.source_url)
        self.assertTrue(
            all(
                request.get_header("Cache-control") == "no-cache"
                for request, _ in requests
            )
        )

    def test_transport_observation_is_timestamped_after_feed_fetch(
        self,
    ) -> None:
        watch = self.by_provider[EarningsProvider.GLOBE_NEWSWIRE]
        completed_at = _RECEIVED_AT + timedelta(milliseconds=25)
        clock_values = iter((_RECEIVED_AT, completed_at))
        client = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                _GLOBE_FEED,
                url=request.full_url,
            ),
            clock=lambda: next(clock_values),
        )

        result = client.poll((watch,))

        self.assertEqual(
            result.candidates[0].received_at,
            completed_at,
        )

    def test_sends_conditional_validator_on_later_poll(self) -> None:
        watch = self.by_provider[EarningsProvider.COMPANY_IR]
        requests = []

        def opener(request, *, timeout):
            requests.append(request)
            return _Response(
                _IR_FEED,
                url=request.full_url,
                extra_headers={
                    "ETag": '"ir-v1"',
                    "Last-Modified": (
                        "Mon, 27 Jul 2026 19:59:59 GMT"
                    ),
                },
            )

        client = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=opener,
        )
        client.poll((watch,), received_at=_RECEIVED_AT)
        client.poll((watch,), received_at=_RECEIVED_AT)

        self.assertEqual(
            requests[1].get_header("If-none-match"),
            '"ir-v1"',
        )
        self.assertEqual(
            requests[1].get_header("If-modified-since"),
            "Mon, 27 Jul 2026 19:59:59 GMT",
        )

    def test_content_length_avoids_waiting_for_connection_close(
        self,
    ) -> None:
        watch = self.by_provider[EarningsProvider.COMPANY_IR]
        response = _Response(
            _IR_FEED,
            url=watch.feed_url,
            extra_headers={
                "Content-Length": str(len(_IR_FEED)),
            },
        )

        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda *_args, **_kwargs: response,
        ).poll((watch,), received_at=_RECEIVED_AT)

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(response.read_sizes, [len(_IR_FEED)])

    def test_accepts_known_html_entity_in_rss_text(self) -> None:
        watch = self.by_provider[EarningsProvider.COMPANY_IR]
        feed = _IR_FEED.replace(
            b"Second Quarter 2026",
            b"Second&nbsp;Quarter 2026",
        )

        result = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                feed,
                url=request.full_url,
            ),
        ).poll((watch,), received_at=_RECEIVED_AT)

        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.error_count, 0)
        self.assertEqual(len(result.candidates), 1)

    def test_failing_feed_is_deferred_without_delaying_healthy_feed(
        self,
    ) -> None:
        clock = [100.0]
        failing_watch = self.by_provider[
            EarningsProvider.COMPANY_IR
        ]
        healthy_watch = self.by_provider[
            EarningsProvider.GLOBE_NEWSWIRE
        ]
        requests: list[str] = []

        def opener(request, *, timeout):
            requests.append(request.full_url)
            if request.full_url == failing_watch.feed_url:
                raise RuntimeError("temporary feed failure")
            return _Response(
                _GLOBE_FEED,
                url=request.full_url,
            )

        client = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=opener,
            monotonic=lambda: clock[0],
            error_backoff_initial=2,
            error_backoff_max=8,
        )

        first = client.poll(
            (failing_watch, healthy_watch),
            received_at=_RECEIVED_AT,
        )
        second = client.poll(
            (failing_watch, healthy_watch),
            received_at=_RECEIVED_AT,
        )

        self.assertEqual(first.error_count, 1)
        self.assertEqual(second.deferred_count, 1)
        self.assertEqual(second.error_count, 0)
        self.assertEqual(
            requests.count(failing_watch.feed_url),
            1,
        )
        self.assertEqual(
            requests.count(healthy_watch.feed_url),
            2,
        )

        clock[0] += 2
        third = client.poll(
            (failing_watch, healthy_watch),
            received_at=_RECEIVED_AT,
        )
        self.assertEqual(third.error_count, 1)
        self.assertEqual(
            requests.count(failing_watch.feed_url),
            2,
        )

    def test_document_fetcher_enforces_scope_host_and_size(self) -> None:
        candidate = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                _GLOBE_FEED,
                url=request.full_url,
            ),
        ).poll(
            (self.by_provider[EarningsProvider.GLOBE_NEWSWIRE],),
            received_at=_RECEIVED_AT,
        ).candidates[0]
        fetcher = PublicReleaseDocumentFetcher(
            watches=self.watches,
            user_agent="CodexPoly test@example.com",
            timeout=3,
            max_bytes=1024,
            opener=lambda request, **_kwargs: _Response(
                b"<html>official release</html>",
                url=request.full_url,
                content_type="text/html",
            ),
        )

        self.assertEqual(
            fetcher.fetch(candidate),
            b"<html>official release</html>",
        )
        self.assertEqual(
            candidate.transport,
            EarningsTransport.GLOBE_NEWSWIRE_POLL,
        )

        bad_candidate = candidate.__class__(
            **{
                **candidate.__dict__,
                "source_url": "https://example.com/release",
            }
        )
        with self.assertRaisesRegex(
            PublicReleaseSourceError,
            "configured domain",
        ):
            fetcher.fetch(bad_candidate)

    def test_rejects_dtd_before_xml_parsing(self) -> None:
        watch = self.by_provider[EarningsProvider.COMPANY_IR]
        client = PublicReleaseFeedClient(
            user_agent="CodexPoly test@example.com",
            timeout=3,
            opener=lambda request, **_kwargs: _Response(
                b"<!DOCTYPE rss><rss/>",
                url=request.full_url,
            ),
        )

        result = client.poll((watch,), received_at=_RECEIVED_AT)

        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.candidates, ())


if __name__ == "__main__":
    unittest.main()
