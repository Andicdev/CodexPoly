from __future__ import annotations

import unittest
from datetime import datetime, timezone
from email.message import Message

from cbr_trading.earnings.contracts import EarningsProvider
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
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        for name, value in (extra_headers or {}).items():
            self.headers[name] = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
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
            ].feed_url.endswith("rss/news-releases.xml")
        )
        self.assertTrue(
            all(watch.kind == "rss" for watch in self.watches)
        )

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
