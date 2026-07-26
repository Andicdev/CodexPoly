from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from cbr_trading.sec_filings import (
    SecStreamTransport,
    normalize_sec_filing,
)


_NOW = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)


class _FakeSocket:
    def __init__(self, messages: list[str]):
        self._messages = messages

    def __aiter__(self):
        self._iterator = iter(self._messages)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


class _FakeConnection:
    def __init__(self, socket: _FakeSocket):
        self._socket = socket

    async def __aenter__(self):
        return self._socket

    async def __aexit__(self, *_: object) -> None:
        return None


class SecFilingEnvelopeTests(unittest.TestCase):
    def test_normalization_is_source_neutral_and_non_semantic(self) -> None:
        envelope = normalize_sec_filing(
            {
                "ticker": "mstr",
                "cik": "0001050446",
                "formType": "8-K",
                "filedAt": "2026-07-27T08:00:01-04:00",
                "items": ["Item 8.01"],
                "documentFormatFiles": [
                    {
                        "type": "8-k",
                        "documentUrl": "https://www.sec.gov/report.htm",
                    }
                ],
            },
            received_at=_NOW,
        )

        self.assertEqual(envelope.ticker, "MSTR")
        self.assertEqual(envelope.cik, "1050446")
        self.assertEqual(envelope.form_type, "8-K")
        self.assertEqual(
            envelope.filed_at,
            datetime(
                2026,
                7,
                27,
                12,
                0,
                1,
                tzinfo=timezone.utc,
            ),
        )
        self.assertEqual(envelope.documents[0].document_type, "8-K")
        self.assertIsNone(envelope.accession)
        self.assertIsNone(envelope.filing_url)


class SecStreamTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_connection_yields_unrouted_envelopes(self) -> None:
        calls = []
        messages = [
            json.dumps(
                [
                    {"ticker": "NVTS", "formType": "8-K"},
                    {"ticker": "MSTR", "formType": "8-K"},
                ]
            )
        ]

        def connect(uri: str, **_kwargs: object) -> _FakeConnection:
            calls.append(uri)
            return _FakeConnection(_FakeSocket(messages))

        transport = SecStreamTransport(
            api_key="test-credential",
            connect_factory=connect,
            clock=lambda: _NOW,
        )
        envelopes = [
            envelope
            async for envelope in transport.stream_once()
        ]

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            [envelope.ticker for envelope in envelopes],
            ["NVTS", "MSTR"],
        )
        self.assertNotIn("test-credential", repr(transport))


if __name__ == "__main__":
    unittest.main()
