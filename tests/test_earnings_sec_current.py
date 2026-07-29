from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from email.message import Message
from urllib.error import HTTPError

from cbr_trading.earnings.contracts import EarningsTransport
from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.sec_current import (
    SecCurrentEarningsWatch,
    SecCurrentFilingsClient,
    sec_current_watches_from_rules,
)
from cbr_trading.earnings.sec_stream import SecStreamFilingRouter


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        url: str,
        content_type: str,
        headers: dict[str, str] | None = None,
        status: int = 200,
    ):
        self._body = body
        self._url = url
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
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


def _payload(
    *,
    acceptance: str = "2026-07-27T16:05:01.000Z",
    items: str = "2.02,9.01",
) -> bytes:
    return json.dumps(
        {
            "cik": 1821769,
            "name": "Navitas Semiconductor Corporation",
            "filings": {
                "recent": {
                    "accessionNumber": [
                        "0001821769-26-000123",
                    ],
                    "acceptanceDateTime": [acceptance],
                    "form": ["8-K"],
                    "items": [items],
                    "primaryDocument": ["nvts-20260727.htm"],
                    "primaryDocDescription": ["8-K"],
                }
            },
        }
    ).encode("utf-8")


def _filing_html() -> bytes:
    return b"""
    <html><body>
      <table class="tableFile" summary="Document Format Files">
        <tr><th>Seq</th><th>Description</th><th>Document</th>
            <th>Type</th><th>Size</th></tr>
        <tr><td>1</td><td>8-K</td>
            <td><a href="/ix?doc=/Archives/edgar/data/1821769/000182176926000123/nvts-20260727.htm">nvts-20260727.htm</a></td>
            <td>8-K</td><td>1000</td></tr>
        <tr><td>2</td><td>PRESS RELEASE</td>
            <td><a href="exhibit991.htm">exhibit991.htm</a></td>
            <td>EX-99.1</td><td>2000</td></tr>
      </table>
    </body></html>
    """


class SecCurrentFilingsClientTests(unittest.TestCase):
    def _client(self, opener, *, sleeps=None, clock=None):
        return SecCurrentFilingsClient(
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

    def test_official_submission_routes_through_existing_sec_router(
        self,
    ) -> None:
        watches = sec_current_watches_from_rules(
            (nvts_q2_2026_shadow_rule(),)
        )
        submissions_url = (
            "https://data.sec.gov/submissions/"
            "CIK0001821769.json"
        )
        filing_url = (
            "https://www.sec.gov/Archives/edgar/data/1821769/"
            "000182176926000123/"
            "0001821769-26-000123-index.html"
        )
        opener = _QueuedOpener(
            (
                _Response(
                    _payload(),
                    url=submissions_url,
                    content_type="application/json",
                    headers={"ETag": '"version-1"'},
                ),
                _Response(
                    _filing_html(),
                    url=filing_url,
                    content_type="text/html",
                ),
            )
        )
        sleeps = []
        client = self._client(opener, sleeps=sleeps)

        result = client.poll(watches)

        self.assertEqual(result.error_count, 0)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(len(result.envelopes), 1)
        envelope = result.envelopes[0]
        self.assertEqual(envelope.items, ("Item 2.02", "Item 9.01"))
        self.assertEqual(
            envelope.metadata["transport"],
            "sec_current_poll",
        )
        self.assertEqual(
            envelope.filed_at.isoformat(),
            "2026-07-27T20:05:01+00:00",
        )
        router = SecStreamFilingRouter(
            tuple(watch.routing_watch for watch in watches)
        )
        decision = router.route(envelope)[0]
        self.assertTrue(decision.accepted)
        self.assertEqual(
            decision.candidate.transport,
            EarningsTransport.SEC_CURRENT_POLL,
        )
        self.assertEqual(
            decision.candidate.source_url,
            (
                "https://www.sec.gov/Archives/edgar/data/1821769/"
                "000182176926000123/exhibit991.htm"
            ),
        )
        self.assertEqual(
            opener.requests[0][0].get_header("User-agent"),
            "CodexPoly test@example.com",
        )
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.2)

    def test_transport_observation_is_timestamped_after_detail_fetch(
        self,
    ) -> None:
        watches = sec_current_watches_from_rules(
            (nvts_q2_2026_shadow_rule(),)
        )
        started_at = datetime(
            2026, 7, 27, 20, 5, 2, tzinfo=timezone.utc
        )
        completed_at = datetime(
            2026, 7, 27, 20, 5, 2, 250000, tzinfo=timezone.utc
        )
        current_time = [started_at]
        responses = iter(
            (
                _Response(
                    _payload(),
                    url=(
                        "https://data.sec.gov/submissions/"
                        "CIK0001821769.json"
                    ),
                    content_type="application/json",
                ),
                _Response(
                    _filing_html(),
                    url=(
                        "https://www.sec.gov/Archives/edgar/data/"
                        "1821769/000182176926000123/"
                        "0001821769-26-000123-index.html"
                    ),
                    content_type="text/html",
                ),
            )
        )
        calls = [0]

        def opener(_request, **_kwargs):
            calls[0] += 1
            if calls[0] == 2:
                current_time[0] = completed_at
            return next(responses)

        result = self._client(
            opener,
            clock=lambda: current_time[0],
        ).poll(watches)

        self.assertEqual(
            result.envelopes[0].received_at,
            completed_at,
        )

    def test_stale_filing_is_ignored_without_detail_request(self) -> None:
        watches = sec_current_watches_from_rules(
            (nvts_q2_2026_shadow_rule(),)
        )
        submissions_url = (
            "https://data.sec.gov/submissions/"
            "CIK0001821769.json"
        )
        opener = _QueuedOpener(
            (
                _Response(
                    _payload(
                        acceptance="2026-01-01T12:00:00.000Z"
                    ),
                    url=submissions_url,
                    content_type="application/json",
                ),
            )
        )

        result = self._client(opener).poll(watches)

        self.assertEqual(result.envelopes, ())
        self.assertEqual(result.success_count, 1)
        self.assertEqual(len(opener.requests), 1)

    def test_acceptance_timestamp_uses_eastern_standard_time(
        self,
    ) -> None:
        base_watch = sec_current_watches_from_rules(
            (nvts_q2_2026_shadow_rule(),)
        )[0]
        watches = (
            SecCurrentEarningsWatch(
                routing_watch=base_watch.routing_watch,
                filed_not_before=datetime(
                    2026,
                    1,
                    1,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        submissions_url = (
            "https://data.sec.gov/submissions/"
            "CIK0001821769.json"
        )
        filing_url = (
            "https://www.sec.gov/Archives/edgar/data/1821769/"
            "000182176926000123/"
            "0001821769-26-000123-index.html"
        )
        opener = _QueuedOpener(
            (
                _Response(
                    _payload(
                        acceptance="2026-01-27T16:05:01.000Z"
                    ),
                    url=submissions_url,
                    content_type="application/json",
                ),
                _Response(
                    _filing_html(),
                    url=filing_url,
                    content_type="text/html",
                ),
            )
        )
        client = SecCurrentFilingsClient(
            user_agent="CodexPoly test@example.com",
            timeout=2,
            opener=opener,
            clock=lambda: datetime(
                2026,
                1,
                27,
                21,
                5,
                2,
                tzinfo=timezone.utc,
            ),
            monotonic=lambda: 100.0,
            sleep=lambda _value: None,
        )

        result = client.poll(watches)

        self.assertEqual(
            result.envelopes[0].filed_at.isoformat(),
            "2026-01-27T21:05:01+00:00",
        )

    def test_conditional_poll_reuses_resolved_envelope(self) -> None:
        watches = sec_current_watches_from_rules(
            (nvts_q2_2026_shadow_rule(),)
        )
        submissions_url = (
            "https://data.sec.gov/submissions/"
            "CIK0001821769.json"
        )
        filing_url = (
            "https://www.sec.gov/Archives/edgar/data/1821769/"
            "000182176926000123/"
            "0001821769-26-000123-index.html"
        )
        not_modified = HTTPError(
            submissions_url,
            304,
            "Not Modified",
            hdrs=None,
            fp=None,
        )
        opener = _QueuedOpener(
            (
                _Response(
                    _payload(),
                    url=submissions_url,
                    content_type="application/json",
                    headers={"ETag": '"version-1"'},
                ),
                _Response(
                    _filing_html(),
                    url=filing_url,
                    content_type="text/html",
                ),
                not_modified,
            )
        )
        client = self._client(opener)

        first = client.poll(watches)
        second = client.poll(watches)

        self.assertEqual(len(first.envelopes), 1)
        self.assertEqual(len(second.envelopes), 1)
        self.assertEqual(second.not_modified_count, 1)
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual(
            opener.requests[2][0].get_header("If-none-match"),
            '"version-1"',
        )

    def test_non_item_202_filing_never_fetches_detail(self) -> None:
        watches = sec_current_watches_from_rules(
            (nvts_q2_2026_shadow_rule(),)
        )
        submissions_url = (
            "https://data.sec.gov/submissions/"
            "CIK0001821769.json"
        )
        opener = _QueuedOpener(
            (
                _Response(
                    _payload(items="8.01,9.01"),
                    url=submissions_url,
                    content_type="application/json",
                ),
            )
        )

        result = self._client(opener).poll(watches)

        self.assertEqual(result.envelopes, ())
        self.assertEqual(len(opener.requests), 1)


if __name__ == "__main__":
    unittest.main()
