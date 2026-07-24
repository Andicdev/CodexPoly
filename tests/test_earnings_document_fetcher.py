from __future__ import annotations

import unittest

from cbr_trading.earnings.document_fetcher import (
    SecDocumentFetchError,
    SecDocumentFetcher,
)
from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from tests.test_earnings_navitas_parser import _source


class _Headers(dict):
    def get_content_type(self) -> str:
        return str(self.get("Content-Type") or "").split(";", 1)[0]


class _Response:
    def __init__(
        self,
        document: bytes,
        *,
        url: str = "https://www.sec.gov/exhibit991.htm",
        content_type: str = "text/html",
    ):
        self._document = document
        self._url = url
        self.headers = _Headers({"Content-Type": content_type})

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, size: int) -> bytes:
        return self._document[:size]


class SecDocumentFetcherTests(unittest.TestCase):
    def test_fetches_bounded_public_sec_document_without_auth(self) -> None:
        requests = []

        def opener(request, *, timeout: float):
            requests.append((request, timeout))
            return _Response(b"<html>earnings</html>")

        fetcher = SecDocumentFetcher(
            user_agent="CodexPoly test agent",
            timeout=7,
            max_bytes=4096,
            opener=opener,
        )
        document = fetcher.fetch(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(document, b"<html>earnings</html>")
        request, timeout = requests[0]
        self.assertEqual(timeout, 7)
        self.assertEqual(
            request.get_header("User-agent"),
            "CodexPoly test agent",
        )
        self.assertIsNone(request.get_header("Authorization"))

    def test_rejects_non_sec_redirect_and_oversized_document(self) -> None:
        redirected = SecDocumentFetcher(
            user_agent="test",
            timeout=5,
            max_bytes=4096,
            opener=lambda *_args, **_kwargs: _Response(
                b"document",
                url="https://example.com/document",
            ),
        )
        with self.assertRaisesRegex(
            SecDocumentFetchError,
            "SEC domain",
        ):
            redirected.fetch(
                _source(nvts_q2_2026_shadow_rule())
            )

        oversized = SecDocumentFetcher(
            user_agent="test",
            timeout=5,
            max_bytes=1024,
            opener=lambda *_args, **_kwargs: _Response(
                b"x" * 1025
            ),
        )
        with self.assertRaisesRegex(
            SecDocumentFetchError,
            "size limit",
        ):
            oversized.fetch(
                _source(nvts_q2_2026_shadow_rule())
            )

    def test_network_exception_is_sanitized_to_type(self) -> None:
        sensitive_detail = "credential-that-must-not-leak"

        def opener(*_args, **_kwargs):
            raise RuntimeError(sensitive_detail)

        fetcher = SecDocumentFetcher(
            user_agent="test",
            timeout=5,
            max_bytes=1024,
            opener=opener,
        )
        with self.assertRaises(SecDocumentFetchError) as caught:
            fetcher.fetch(
                _source(nvts_q2_2026_shadow_rule())
            )

        self.assertNotIn(sensitive_detail, str(caught.exception))
        self.assertIn("RuntimeError", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
