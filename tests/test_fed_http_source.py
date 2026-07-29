from __future__ import annotations

import unittest
from datetime import datetime, timezone
from threading import Event, Lock
from time import monotonic
from unittest.mock import patch

from cbr_trading.fed import (
    FedDocumentKind,
    FedDocumentRoute,
    FedOfficialDocumentPoller,
    FedRouteResponse,
    fed_july_2026_decision_spec,
)


_NOW = datetime(2026, 7, 29, 18, tzinfo=timezone.utc)
_HTML = b"""
<html><body>
July 29, 2026
The Committee decided to maintain the target range for the
federal funds rate at 3-1/2 to 3-3/4 percent.
</body></html>
"""


class _Transport:
    def __init__(self, responses: dict[str, FedRouteResponse]):
        self.responses = responses
        self.calls: list[str] = []
        self.closed = False

    def fetch(
        self,
        route: FedDocumentRoute,
        *,
        timeout: tuple[float, float],
        max_bytes: int,
    ) -> FedRouteResponse:
        del timeout, max_bytes
        self.calls.append(route.name)
        return self.responses.get(
            route.name,
            FedRouteResponse(
                status_code=404,
                content_type="text/html",
                body=b"",
                final_url=route.url,
            ),
        )

    def close(self) -> None:
        self.closed = True


class _SlowMissTransport(_Transport):
    def __init__(self, statement_url: str):
        super().__init__({})
        self.statement_url = statement_url
        self.release_slow_route = Event()
        self._call_counts: dict[str, int] = {}
        self._call_lock = Lock()

    def fetch(
        self,
        route: FedDocumentRoute,
        *,
        timeout: tuple[float, float],
        max_bytes: int,
    ) -> FedRouteResponse:
        del timeout, max_bytes
        with self._call_lock:
            self.calls.append(route.name)
            call_number = self._call_counts.get(route.name, 0) + 1
            self._call_counts[route.name] = call_number
        if route.name == "new_york_fed_statement_pdf":
            self.release_slow_route.wait(timeout=1)
        if (
            route.name == "fed_board_statement_html"
            and call_number >= 2
        ):
            return FedRouteResponse(
                status_code=200,
                content_type="text/html",
                body=_HTML,
                final_url=self.statement_url,
            )
        return FedRouteResponse(
            status_code=404,
            content_type="text/html",
            body=b"",
            final_url=route.url,
        )


class _ReplayTransport(_Transport):
    def __init__(self, statement_url: str, *, release_attempt: int):
        super().__init__({})
        self.statement_url = statement_url
        self.release_attempt = release_attempt
        self._statement_attempts = 0
        self._call_lock = Lock()

    def fetch(
        self,
        route: FedDocumentRoute,
        *,
        timeout: tuple[float, float],
        max_bytes: int,
    ) -> FedRouteResponse:
        del timeout, max_bytes
        with self._call_lock:
            self.calls.append(route.name)
            if route.name == "fed_board_statement_html":
                self._statement_attempts += 1
                if self._statement_attempts >= self.release_attempt:
                    return FedRouteResponse(
                        status_code=200,
                        content_type="text/html",
                        body=_HTML,
                        final_url=self.statement_url,
                    )
        return FedRouteResponse(
            status_code=404,
            content_type="text/html",
            body=b"",
            final_url=route.url,
        )


class _AdvancingMonotonic:
    def __init__(self) -> None:
        self._value = 0.0
        self._lock = Lock()

    def __call__(self) -> float:
        with self._lock:
            self._value += 0.01
            return self._value


class FedHttpSourceTests(unittest.TestCase):
    def test_board_pdf_is_an_independent_direct_route(self) -> None:
        spec = fed_july_2026_decision_spec()
        transport = _Transport(
            {
                "fed_board_statement_pdf": FedRouteResponse(
                    status_code=200,
                    content_type="application/pdf",
                    body=b"%PDF-public-test",
                    final_url=spec.board_statement_pdf_url,
                )
            }
        )
        poller = FedOfficialDocumentPoller(
            spec,
            transport=transport,
            pdf_text_extractor=lambda _document: (
                "July 29, 2026 target range for the federal funds "
                "rate at 3-1/2 to 3-3/4 percent"
            ),
            clock=lambda: _NOW,
        )

        observation = poller.poll_once()

        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(
            observation.provider,
            "fed_board_statement_pdf",
        )
        telemetry = {
            row.route_name: row
            for row in poller.route_telemetry
        }
        pdf = telemetry["fed_board_statement_pdf"]
        self.assertEqual(pdf.attempts, 1)
        self.assertEqual(pdf.http_successes, 1)
        self.assertEqual(pdf.decisions, 1)
        self.assertEqual(pdf.last_status_code, 200)
        self.assertEqual(
            pdf.last_response_bytes,
            len(b"%PDF-public-test"),
        )
        self.assertIsNone(pdf.last_error_type)
        poller.close()

    def test_pdf_route_can_win_when_board_pages_are_unpublished(self) -> None:
        spec = fed_july_2026_decision_spec()
        transport = _Transport(
            {
                "new_york_fed_statement_pdf": FedRouteResponse(
                    status_code=200,
                    content_type="application/pdf",
                    body=b"%PDF-public-test",
                    final_url=spec.new_york_fed_pdf_url,
                )
            }
        )
        poller = FedOfficialDocumentPoller(
            spec,
            transport=transport,
            pdf_text_extractor=lambda _document: (
                "July 29, 2026 target range for the federal funds "
                "rate at 3-1/2 to 3-3/4 percent"
            ),
            clock=lambda: _NOW,
        )

        observation = poller.poll_once()

        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(
            observation.provider,
            "new_york_fed_statement_pdf",
        )
        self.assertEqual(str(observation.decision.upper), "3.75")
        self.assertIs(poller.poll_once(), observation)
        poller.close()
        self.assertTrue(transport.closed)

    def test_rss_discovers_and_fetches_canonical_statement(self) -> None:
        spec = fed_july_2026_decision_spec()
        rss = f"""
        <rss><channel><item>
          <title>Federal Reserve issues FOMC statement</title>
          <guid>not-the-canonical-statement</guid>
          <link>{spec.board_statement_url}</link>
        </item></channel></rss>
        """.encode()
        transport = _Transport(
            {
                "fed_monetary_policy_rss": FedRouteResponse(
                    status_code=200,
                    content_type="text/xml",
                    body=rss,
                    final_url=spec.monetary_policy_rss_url,
                ),
                "board_statement_rss_discovered": FedRouteResponse(
                    status_code=200,
                    content_type="text/html",
                    body=_HTML,
                    final_url=spec.board_statement_url,
                ),
            }
        )
        poller = FedOfficialDocumentPoller(
            spec,
            transport=transport,
            clock=lambda: _NOW,
        )

        observation = poller.poll_once()

        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(
            observation.provider,
            "board_statement_rss_discovered",
        )
        self.assertIn(
            "board_statement_rss_discovered",
            transport.calls,
        )
        poller.close()

    def test_replay_detects_release_after_repeated_misses(self) -> None:
        spec = fed_july_2026_decision_spec()
        transport = _ReplayTransport(
            spec.board_statement_url,
            release_attempt=12,
        )
        poller = FedOfficialDocumentPoller(
            spec,
            transport=transport,
            pdf_text_extractor=lambda _document: "",
            clock=lambda: _NOW,
            monotonic_clock=_AdvancingMonotonic(),
            primary_interval=0.001,
            secondary_interval=0.001,
            poll_wait=0.01,
        )

        observation = None
        for _attempt in range(30):
            observation = poller.poll_once()
            if observation is not None:
                break

        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(
            observation.provider,
            "fed_board_statement_html",
        )
        telemetry = {
            row.route_name: row
            for row in poller.route_telemetry
        }
        statement = telemetry["fed_board_statement_html"]
        self.assertEqual(statement.attempts, 12)
        self.assertEqual(statement.http_successes, 1)
        self.assertEqual(statement.decisions, 1)
        self.assertGreaterEqual(statement.last_total_ms, 0)
        poller.close()

    def test_slow_route_does_not_block_next_board_attempt(self) -> None:
        spec = fed_july_2026_decision_spec()
        transport = _SlowMissTransport(spec.board_statement_url)
        poller = FedOfficialDocumentPoller(
            spec,
            transport=transport,
            pdf_text_extractor=lambda _document: "",
            clock=lambda: _NOW,
            primary_interval=0.001,
            secondary_interval=0.001,
            poll_wait=0.02,
        )

        started = monotonic()
        first = poller.poll_once()
        first_elapsed = monotonic() - started
        second = poller.poll_once()

        self.assertIsNone(first)
        self.assertLess(first_elapsed, 0.2)
        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(
            second.provider,
            "fed_board_statement_html",
        )
        self.assertGreaterEqual(
            transport.calls.count("fed_board_statement_html"),
            2,
        )
        transport.release_slow_route.set()
        poller.close()

    def test_default_pdf_parser_uses_first_page_fast_path(self) -> None:
        spec = fed_july_2026_decision_spec()
        transport = _Transport(
            {
                "fed_board_statement_pdf": FedRouteResponse(
                    status_code=200,
                    content_type="application/pdf",
                    body=b"%PDF-public-test",
                    final_url=spec.board_statement_pdf_url,
                )
            }
        )
        text = (
            "July 29, 2026 target range for the federal funds "
            "rate at 3-1/2 to 3-3/4 percent"
        )
        with patch(
            "cbr_trading.fed.http_source._extract_pdf_text",
            return_value=text,
        ) as extract:
            poller = FedOfficialDocumentPoller(
                spec,
                transport=transport,
                clock=lambda: _NOW,
            )
            observation = poller.poll_once()

        self.assertIsNotNone(observation)
        extract.assert_called_once_with(
            b"%PDF-public-test",
            max_pages=1,
        )
        poller.close()

    def test_route_contract_rejects_non_allowlisted_host(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "allowlisted",
        ):
            FedDocumentRoute(
                name="bad",
                url="https://example.test/release",
                kind=FedDocumentKind.HTML,
                allowed_host="www.federalreserve.gov",
            )


if __name__ == "__main__":
    unittest.main()
