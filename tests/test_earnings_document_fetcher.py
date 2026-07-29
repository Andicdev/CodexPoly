from __future__ import annotations

import gzip
import logging
import threading
import unittest
from dataclasses import replace

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
        url: str,
        content_type: str = "text/html",
        content_encoding: str | None = None,
    ):
        self._document = document
        self._url = url
        self.headers = _Headers({"Content-Type": content_type})
        if content_encoding is not None:
            self.headers["Content-Encoding"] = content_encoding

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, size: int) -> bytes:
        return self._document[:size]


class SecDocumentFetcherTests(unittest.TestCase):
    def test_direct_route_can_win_without_forwarding_auth(self) -> None:
        direct_requests = []
        archive_requests = []
        archive_started = threading.Event()
        release_archive = threading.Event()

        def direct_opener(request, *, timeout: float):
            direct_requests.append((request, timeout))
            if not archive_started.wait(1):
                raise AssertionError("archive route did not start")
            return _Response(
                b"<html>direct</html>",
                url=request.full_url,
            )

        def archive_opener(request, *, timeout: float):
            archive_requests.append((request, timeout))
            archive_started.set()
            release_archive.wait(1)
            return _Response(
                b"<html>archive</html>",
                url=request.full_url,
            )

        fetcher = SecDocumentFetcher(
            api_key="test-api-key",
            user_agent="CodexPoly test@example.com",
            timeout=7,
            max_bytes=4096,
            direct_opener=direct_opener,
            archive_opener=archive_opener,
        )
        try:
            document = fetcher.fetch(
                _source(nvts_q2_2026_shadow_rule())
            )
        finally:
            release_archive.set()

        self.assertEqual(document, b"<html>direct</html>")
        request, timeout = direct_requests[0]
        self.assertEqual(timeout, 7)
        self.assertEqual(
            request.get_header("User-agent"),
            "CodexPoly test@example.com",
        )
        self.assertIsNone(request.get_header("Authorization"))
        archive_request, _ = archive_requests[0]
        self.assertEqual(
            archive_request.full_url,
            (
                "https://archive.sec-api.io/1821769/"
                "000000000026000001/exhibit991.htm"
            ),
        )
        self.assertEqual(
            archive_request.get_header("Authorization"),
            "test-api-key",
        )
        self.assertNotIn("test-api-key", archive_request.full_url)

    def test_fetch_result_exposes_winning_route(self) -> None:
        def direct_opener(request, *, timeout: float):
            return _Response(
                b"<html>direct</html>",
                url=request.full_url,
            )

        def archive_opener(*_args, **_kwargs):
            raise RuntimeError("archive unavailable")

        fetcher = SecDocumentFetcher(
            api_key="test-api-key",
            user_agent="CodexPoly test@example.com",
            timeout=5,
            max_bytes=4096,
            direct_opener=direct_opener,
            archive_opener=archive_opener,
        )

        result = fetcher.fetch_with_result(
            _source(nvts_q2_2026_shadow_rule())
        )

        self.assertEqual(result.document, b"<html>direct</html>")
        self.assertEqual(result.route, "sec_direct")

    def test_archive_route_can_win_without_waiting_for_direct(self) -> None:
        release_direct = threading.Event()

        def direct_opener(request, *, timeout: float):
            release_direct.wait(1)
            return _Response(
                b"<html>direct</html>",
                url=request.full_url,
            )

        def archive_opener(request, *, timeout: float):
            return _Response(
                b"<html>archive</html>",
                url=request.full_url,
            )

        fetcher = SecDocumentFetcher(
            api_key="test-api-key",
            user_agent="CodexPoly test@example.com",
            timeout=5,
            max_bytes=4096,
            direct_opener=direct_opener,
            archive_opener=archive_opener,
        )
        try:
            document = fetcher.fetch(
                _source(nvts_q2_2026_shadow_rule())
            )
        finally:
            release_direct.set()

        self.assertEqual(document, b"<html>archive</html>")

    def test_rejects_invalid_redirects_and_oversized_documents(self) -> None:
        redirected = SecDocumentFetcher(
            api_key="test-api-key",
            user_agent="test",
            timeout=5,
            max_bytes=4096,
            direct_opener=lambda *_args, **_kwargs: _Response(
                b"document",
                url="https://example.com/document",
            ),
            archive_opener=lambda *_args, **_kwargs: _Response(
                b"document",
                url="https://example.com/document",
            ),
        )
        with self.assertRaisesRegex(
            SecDocumentFetchError,
            "all configured routes",
        ):
            redirected.fetch(
                _source(nvts_q2_2026_shadow_rule())
            )

        oversized = SecDocumentFetcher(
            api_key="test-api-key",
            user_agent="test",
            timeout=5,
            max_bytes=1024,
            direct_opener=lambda request, **_kwargs: _Response(
                b"x" * 1025,
                url=request.full_url,
            ),
            archive_opener=lambda request, **_kwargs: _Response(
                b"x" * 1025,
                url=request.full_url,
            ),
        )
        with self.assertRaisesRegex(
            SecDocumentFetchError,
            "all configured routes",
        ):
            oversized.fetch(
                _source(nvts_q2_2026_shadow_rule())
            )

    def test_inline_viewer_url_is_normalized_for_both_routes(self) -> None:
        requests = []
        both_routes_started = threading.Barrier(2)

        def opener(request, *, timeout: float):
            requests.append(request)
            both_routes_started.wait(1)
            return _Response(b"document", url=request.full_url)

        candidate = replace(
            _source(nvts_q2_2026_shadow_rule()),
            source_url=(
                "https://www.sec.gov/ix?doc=/Archives/edgar/data/"
                "1821769/000000000026000001/exhibit991.htm"
            ),
        )
        fetcher = SecDocumentFetcher(
            api_key="test-api-key",
            user_agent="test",
            timeout=5,
            max_bytes=1024,
            direct_opener=opener,
            archive_opener=opener,
        )

        self.assertEqual(fetcher.fetch(candidate), b"document")
        requested_urls = {request.full_url for request in requests}
        self.assertIn(
            (
                "https://www.sec.gov/Archives/edgar/data/"
                "1821769/000000000026000001/exhibit991.htm"
            ),
            requested_urls,
        )
        self.assertIn(
            (
                "https://archive.sec-api.io/1821769/"
                "000000000026000001/exhibit991.htm"
            ),
            requested_urls,
        )

    def test_failures_and_repr_do_not_reveal_credentials(self) -> None:
        sensitive_detail = "credential-that-must-not-leak"
        logger = logging.getLogger("test.sec-fetch")
        logger.disabled = True

        def opener(*_args, **_kwargs):
            raise RuntimeError(sensitive_detail)

        fetcher = SecDocumentFetcher(
            api_key=sensitive_detail,
            user_agent="test",
            timeout=5,
            max_bytes=1024,
            direct_opener=opener,
            archive_opener=opener,
            logger=logger,
        )
        with self.assertRaises(SecDocumentFetchError) as caught:
            fetcher.fetch(
                _source(nvts_q2_2026_shadow_rule())
            )

        self.assertNotIn(sensitive_detail, str(caught.exception))
        self.assertNotIn(sensitive_detail, repr(fetcher))

    def test_sec_access_control_page_does_not_beat_archive(self) -> None:
        def direct_opener(request, *, timeout: float):
            return _Response(
                (
                    b"<html>Your Request Originates from an "
                    b"Undeclared Automated Tool</html>"
                ),
                url=request.full_url,
            )

        def archive_opener(request, *, timeout: float):
            return _Response(
                b"<html>valid earnings release</html>",
                url=request.full_url,
            )

        fetcher = SecDocumentFetcher(
            api_key="test-api-key",
            user_agent="CodexPoly test@example.com",
            timeout=5,
            max_bytes=4096,
            direct_opener=direct_opener,
            archive_opener=archive_opener,
        )

        self.assertEqual(
            fetcher.fetch(_source(nvts_q2_2026_shadow_rule())),
            b"<html>valid earnings release</html>",
        )

    def test_gzip_encoded_sec_document_is_decoded_before_parsing(self) -> None:
        payload = b"<html>valid compressed earnings release</html>"

        def direct_opener(request, *, timeout: float):
            return _Response(
                gzip.compress(payload),
                url=request.full_url,
                content_encoding="gzip",
            )

        def archive_opener(*_args, **_kwargs):
            raise RuntimeError("archive unavailable")

        fetcher = SecDocumentFetcher(
            api_key="test-api-key",
            user_agent="CodexPoly test@example.com",
            timeout=5,
            max_bytes=4096,
            direct_opener=direct_opener,
            archive_opener=archive_opener,
        )

        self.assertEqual(
            fetcher.fetch(_source(nvts_q2_2026_shadow_rule())),
            payload,
        )

    def test_rejects_gzip_document_exceeding_uncompressed_limit(self) -> None:
        payload = gzip.compress(b"x" * 1025)

        def opener(request, **_kwargs):
            return _Response(
                payload,
                url=request.full_url,
                content_encoding="gzip",
            )

        fetcher = SecDocumentFetcher(
            api_key="test-api-key",
            user_agent="test",
            timeout=5,
            max_bytes=1024,
            direct_opener=opener,
            archive_opener=opener,
        )

        with self.assertRaisesRegex(
            SecDocumentFetchError,
            "all configured routes",
        ):
            fetcher.fetch(
                _source(nvts_q2_2026_shadow_rule())
            )


if __name__ == "__main__":
    unittest.main()
