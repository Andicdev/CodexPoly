from __future__ import annotations

import unittest
from datetime import datetime, timezone

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


class FedHttpSourceTests(unittest.TestCase):
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
