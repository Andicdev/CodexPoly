from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from cbr_trading.client import (
    CbrClient,
    CbrClientConfig,
    FetchResult,
    RequestsTransport,
    _decode_prefix,
)
from cbr_trading.release import (
    build_predicted_release_url,
    classify_change,
    parse_release_rate_from_title,
)


class FakeTransport:
    def __init__(
        self,
        prefix: FetchResult,
    ):
        self.prefix = prefix
        self.prefix_urls: list[str] = []

    def fetch_prefix(self, url: str, **_: object) -> FetchResult:
        self.prefix_urls.append(url)
        return FetchResult(
            request_url=url,
            status_code=self.prefix.status_code,
            content_type=self.prefix.content_type,
            text=self.prefix.text,
        )

class ReleaseParsingTests(unittest.TestCase):
    def test_builds_expected_release_url(self) -> None:
        url = build_predicted_release_url(
            now=datetime(2026, 7, 23, tzinfo=timezone.utc)
        )
        self.assertEqual(
            url,
            "https://www.cbr.ru/eng/press/pr/?file=23072026_133000key_e.htm",
        )

    def test_release_date_override_accepts_legacy_format(self) -> None:
        url = build_predicted_release_url(
            now=datetime(2026, 7, 23, tzinfo=timezone.utc),
            release_date="13.02.2026",
        )
        self.assertIn("13022026_133000key_e.htm", url)

    def test_parses_rate_changes_from_titles(self) -> None:
        samples = {
            "Bank of Russia cuts the key rate to 18.00% p.a.": 18.0,
            "Bank of Russia raises the key rate by 100 bp to 20%": 20.0,
            "Bank of Russia keeps the key rate at 21.00%": 21.0,
        }
        for title, expected in samples.items():
            with self.subTest(title=title):
                self.assertEqual(
                    parse_release_rate_from_title(title),
                    expected,
                )

    def test_classifies_increase_decrease_and_hold(self) -> None:
        self.assertEqual(classify_change(18.0, 19.0), (100.0, "increase"))
        self.assertEqual(classify_change(19.0, 18.0), (-100.0, "decrease"))
        self.assertEqual(classify_change(18.0, 18.0), (0.0, "no_change"))

class ReleaseDiscoveryTests(unittest.TestCase):
    def test_fetch_error_preserves_http_status(self) -> None:
        class HttpError(Exception):
            def __init__(self) -> None:
                super().__init__("403 Client Error")
                self.response = SimpleNamespace(status_code=403)

        class FailingTransport:
            def fetch_prefix(
                self,
                url: str,
                **_: object,
            ) -> FetchResult:
                raise HttpError()

        result = CbrClient(
            FailingTransport(),
            CbrClientConfig(cache_bust=False),
        ).discover_predicted_release(
            now=datetime(2026, 7, 23, tzinfo=timezone.utc)
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "fetch_failed")
        self.assertEqual(result.status_code, 403)

    def test_404_means_not_published(self) -> None:
        transport = FakeTransport(
            FetchResult("", 404, "text/html", "")
        )
        result = CbrClient(
            transport,
            CbrClientConfig(cache_bust=False),
        ).discover_predicted_release(
            now=datetime(2026, 7, 23, tzinfo=timezone.utc)
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_published_yet")
        self.assertEqual(result.status_code, 404)

    def test_detects_published_release_from_title(self) -> None:
        transport = FakeTransport(
            FetchResult(
                "",
                200,
                "text/html",
                (
                    "<html><title>Bank of Russia cuts the key rate "
                    "to 18.00% p.a.</title></html>"
                ),
            )
        )
        result = CbrClient(
            transport,
            CbrClientConfig(cache_bust=False),
        ).discover_predicted_release(
            now=datetime(2026, 7, 23, tzinfo=timezone.utc)
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "published")
        self.assertEqual(result.new_rate, 18.0)

    def test_rate_in_body_is_not_used(self) -> None:
        transport = FakeTransport(
            FetchResult(
                "",
                200,
                "text/html",
                (
                    "<html><title>Bank of Russia press release</title>"
                    "<p>The Board of Directors decided to keep the key rate "
                    "at 17.00% per annum.</p></html>"
                ),
            ),
        )
        result = CbrClient(
            transport,
            CbrClientConfig(cache_bust=False),
        ).discover_predicted_release(
            now=datetime(2026, 7, 23, tzinfo=timezone.utc)
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_published_yet")
        self.assertIsNone(result.new_rate)

    def test_cache_buster_is_added(self) -> None:
        transport = FakeTransport(
            FetchResult("", 404, "text/html", "")
        )
        CbrClient(
            transport,
            CbrClientConfig(cache_bust=True),
        ).discover_predicted_release(
            now=datetime(2026, 7, 23, tzinfo=timezone.utc)
        )
        self.assertIn("&_ts=", transport.prefix_urls[0])


class RequestsTransportTests(unittest.TestCase):
    def test_corrects_false_utf8_header_for_placeholder_title(self) -> None:
        payload = (
            "<html><title>Пресс-релиз | Bank of Russia</title></html>"
        ).encode("cp1251")
        decoded = _decode_prefix(
            payload,
            declared_encoding="utf-8",
        )
        self.assertIn("Пресс-релиз", decoded)

    def test_network_error_does_not_trigger_second_request(self) -> None:
        class FakeRequestError(Exception):
            pass

        class FailingSession:
            def __init__(self) -> None:
                self.calls = 0

            def get(self, *_: object, **__: object) -> object:
                self.calls += 1
                raise FakeRequestError("timeout")

        session = FailingSession()
        transport = RequestsTransport.__new__(RequestsTransport)
        transport._session = session
        transport._requests = SimpleNamespace(
            RequestException=FakeRequestError,
        )

        with self.assertRaises(FakeRequestError):
            transport.fetch_prefix(
                "https://example.invalid/release",
                connect_timeout=0.5,
                read_timeout=0.5,
                max_bytes=32768,
                chunk_size=2048,
            )

        self.assertEqual(session.calls, 1)


if __name__ == "__main__":
    unittest.main()
