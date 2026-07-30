from __future__ import annotations

import unittest
from datetime import datetime, timezone
from email.message import Message
from urllib.error import HTTPError

from cbr_trading.earnings.contracts import EarningsTransport
from cbr_trading.earnings.parsers import checked_in_shadow_rules
from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.sec_latest import (
    SEC_LATEST_FILINGS_ATOM_URL,
    SecLatestFilingsClient,
    sec_latest_watches_from_rules,
)
from cbr_trading.earnings.sec_stream import SecStreamFilingRouter


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        status: int = 200,
    ):
        self._body = body
        self._url = url
        self.status = status
        self.headers = Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _QueuedOpener:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def __call__(self, request, *, timeout):
        self.requests.append((request, timeout))
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _atom_feed(
    *,
    updated: str = "2026-07-27T16:05:01-04:00",
    summary: str = (
        "&lt;b&gt;Filed:&lt;/b&gt; 2026-07-27 "
        "&lt;b&gt;AccNo:&lt;/b&gt; 0001821769-26-000123 "
        "&lt;br&gt;Item 2.02: Results of Operations and "
        "Financial Condition&lt;br&gt;"
        "Item 9.01: Financial Statements and Exhibits"
    ),
) -> bytes:
    filing_url = (
        "https://www.sec.gov/Archives/edgar/data/1821769/"
        "000182176926000123/"
        "0001821769-26-000123-index.htm"
    )
    unwatched_url = (
        "https://www.sec.gov/Archives/edgar/data/123/"
        "000000012326000001/"
        "0000000123-26-000001-index.htm"
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Latest Filings</title>
      <entry>
        <title>8-K - Navitas Semiconductor Corporation
          (0001821769) (Filer)</title>
        <link rel="alternate" type="text/html"
          href="{filing_url}" />
        <summary type="html">{summary}</summary>
        <updated>{updated}</updated>
        <category scheme="https://www.sec.gov/"
          label="form type" term="8-K" />
        <id>urn:tag:sec.gov,2008:accession-number=0001821769-26-000123</id>
      </entry>
      <entry>
        <title>8-K - Unwatched Issuer (0000000123) (Filer)</title>
        <link rel="alternate" type="text/html"
          href="{unwatched_url}" />
        <summary type="html">Item 2.02: Results of Operations</summary>
        <updated>{updated}</updated>
        <category scheme="https://www.sec.gov/"
          label="form type" term="8-K" />
        <id>urn:tag:sec.gov,2008:accession-number=0000000123-26-000001</id>
      </entry>
    </feed>""".encode("utf-8")


def _filing_html() -> bytes:
    return b"""
    <html><body>
      <table class="tableFile" summary="Document Format Files">
        <tr><th>Seq</th><th>Description</th><th>Document</th>
            <th>Type</th><th>Size</th></tr>
        <tr><td>1</td><td>8-K</td>
            <td><a href="/ix?doc=/Archives/edgar/data/1821769/
              000182176926000123/nvts-20260727.htm">
              nvts-20260727.htm</a></td>
            <td>8-K</td><td>1000</td></tr>
        <tr><td>2</td><td>PRESS RELEASE</td>
            <td><a href="exhibit991.htm">exhibit991.htm</a></td>
            <td>EX-99.1</td><td>2000</td></tr>
      </table>
    </body></html>
    """


class SecLatestFilingsClientTests(unittest.TestCase):
    def _client(self, opener, *, sleeps=None, clock=None):
        return SecLatestFilingsClient(
            user_agent="CodexPoly test@example.com",
            timeout=2,
            opener=opener,
            clock=clock or (
                lambda: datetime(
                    2026,
                    7,
                    27,
                    20,
                    5,
                    2,
                    tzinfo=timezone.utc,
                )
            ),
            monotonic=lambda: 100.0,
            sleep=(
                (lambda value: sleeps.append(value))
                if sleeps is not None
                else (lambda _value: None)
            ),
        )

    def test_shared_feed_routes_matching_filing_through_sec_router(
        self,
    ) -> None:
        filing_url = (
            "https://www.sec.gov/Archives/edgar/data/1821769/"
            "000182176926000123/"
            "0001821769-26-000123-index.htm"
        )
        opener = _QueuedOpener(
            (
                _Response(
                    _atom_feed(),
                    url=SEC_LATEST_FILINGS_ATOM_URL,
                    headers={"ETag": '"feed-version-1"'},
                ),
                _Response(
                    _filing_html(),
                    url=filing_url,
                ),
            )
        )
        sleeps = []
        watches = sec_latest_watches_from_rules(
            (nvts_q2_2026_shadow_rule(),)
        )
        result = self._client(
            opener,
            sleeps=sleeps,
        ).poll(watches)

        self.assertEqual(result.error_count, 0)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(len(result.envelopes), 1)
        envelope = result.envelopes[0]
        self.assertEqual(envelope.cik, "1821769")
        self.assertEqual(
            envelope.filed_at.isoformat(),
            "2026-07-27T20:05:01+00:00",
        )
        self.assertEqual(
            envelope.metadata["transport"],
            "sec_latest_filings_atom",
        )
        router = SecStreamFilingRouter(
            tuple(watch.routing_watch for watch in watches)
        )
        decision = router.route(envelope)[0]
        self.assertTrue(decision.accepted)
        self.assertEqual(
            decision.candidate.transport,
            EarningsTransport.SEC_LATEST_FILINGS_ATOM,
        )
        self.assertEqual(
            decision.candidate.source_url,
            (
                "https://www.sec.gov/Archives/edgar/data/1821769/"
                "000182176926000123/exhibit991.htm"
            ),
        )
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual(
            opener.requests[0][0].get_header("User-agent"),
            "CodexPoly test@example.com",
        )
        self.assertEqual(sleeps, [0.2])

    def test_no_watches_means_no_feed_request(self) -> None:
        opener = _QueuedOpener(())

        result = self._client(opener).poll(())

        self.assertEqual(result.envelopes, ())
        self.assertEqual(result.watch_count, 0)
        self.assertEqual(opener.requests, [])

    def test_transport_timestamp_is_feed_arrival_not_detail_finish(
        self,
    ) -> None:
        filing_url = (
            "https://www.sec.gov/Archives/edgar/data/1821769/"
            "000182176926000123/"
            "0001821769-26-000123-index.htm"
        )
        opener = _QueuedOpener(
            (
                _Response(
                    _atom_feed(),
                    url=SEC_LATEST_FILINGS_ATOM_URL,
                ),
                _Response(
                    _filing_html(),
                    url=filing_url,
                ),
            )
        )
        feed_arrival = datetime(
            2026, 7, 27, 20, 5, 2, tzinfo=timezone.utc
        )
        detail_finish = datetime(
            2026,
            7,
            27,
            20,
            5,
            2,
            400000,
            tzinfo=timezone.utc,
        )
        timestamps = iter((feed_arrival, detail_finish))

        result = self._client(
            opener,
            clock=lambda: next(timestamps),
        ).poll(
            sec_latest_watches_from_rules(
                (nvts_q2_2026_shadow_rule(),)
            )
        )

        self.assertEqual(
            result.envelopes[0].received_at,
            feed_arrival,
        )

    def test_one_feed_request_covers_multiple_active_issuers(
        self,
    ) -> None:
        rules = tuple(
            rule
            for rule in checked_in_shadow_rules()
            if rule.ticker in {"NVTS", "WWD"}
        )
        opener = _QueuedOpener(
            (
                _Response(
                    _atom_feed(summary="Item 8.01: Other Events"),
                    url=SEC_LATEST_FILINGS_ATOM_URL,
                ),
            )
        )

        result = self._client(opener).poll(
            sec_latest_watches_from_rules(rules)
        )

        self.assertEqual(result.watch_count, 2)
        self.assertEqual(result.envelopes, ())
        self.assertEqual(len(opener.requests), 1)

    def test_conditional_poll_reuses_resolved_envelope(self) -> None:
        filing_url = (
            "https://www.sec.gov/Archives/edgar/data/1821769/"
            "000182176926000123/"
            "0001821769-26-000123-index.htm"
        )
        not_modified = HTTPError(
            SEC_LATEST_FILINGS_ATOM_URL,
            304,
            "Not Modified",
            hdrs=None,
            fp=None,
        )
        opener = _QueuedOpener(
            (
                _Response(
                    _atom_feed(),
                    url=SEC_LATEST_FILINGS_ATOM_URL,
                    headers={"ETag": '"feed-version-1"'},
                ),
                _Response(
                    _filing_html(),
                    url=filing_url,
                ),
                not_modified,
            )
        )
        client = self._client(opener)
        watches = sec_latest_watches_from_rules(
            (nvts_q2_2026_shadow_rule(),)
        )

        first = client.poll(watches)
        second = client.poll(watches)

        self.assertEqual(len(first.envelopes), 1)
        self.assertEqual(len(second.envelopes), 1)
        self.assertEqual(second.not_modified_count, 1)
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual(
            opener.requests[2][0].get_header("If-none-match"),
            '"feed-version-1"',
        )

    def test_stale_entry_is_ignored_before_filing_request(self) -> None:
        opener = _QueuedOpener(
            (
                _Response(
                    _atom_feed(
                        updated="2026-01-01T12:00:00-05:00"
                    ),
                    url=SEC_LATEST_FILINGS_ATOM_URL,
                ),
            )
        )

        result = self._client(opener).poll(
            sec_latest_watches_from_rules(
                (nvts_q2_2026_shadow_rule(),)
            )
        )

        self.assertEqual(result.envelopes, ())
        self.assertEqual(len(opener.requests), 1)

    def test_unapproved_feed_redirect_fails_closed(self) -> None:
        opener = _QueuedOpener(
            (
                _Response(
                    _atom_feed(),
                    url="https://example.com/feed.atom",
                ),
            )
        )

        result = self._client(opener).poll(
            sec_latest_watches_from_rules(
                (nvts_q2_2026_shadow_rule(),)
            )
        )

        self.assertEqual(result.envelopes, ())
        self.assertEqual(result.error_count, 1)
        self.assertEqual(len(opener.requests), 1)


if __name__ == "__main__":
    unittest.main()
