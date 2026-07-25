from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from cbr_trading.earnings.sec_stream import (
    SecEarningsWatch,
    SecStreamEarningsTransport,
    SecStreamTransportError,
    _stream_error_code,
    decode_sec_stream_message,
    evaluate_sec_earnings_filing,
)


_NOW = datetime(2026, 7, 27, 21, 0, 1, tzinfo=timezone.utc)
_WATCH = SecEarningsWatch(
    scope_id="earnings:NVTS:2026Q2",
    ticker="NVTS",
    cik="1821769",
)


def _filing(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "ticker": "NVTS",
        "cik": "0001821769",
        "companyName": "Navitas Semiconductor Corporation",
        "accessionNo": "0001104659-26-123456",
        "formType": "8-K",
        "filedAt": "2026-07-27T17:00:04-04:00",
        "items": [
            "Item 2.02: Results of Operations and Financial Condition",
            "Item 9.01: Financial Statements and Exhibits",
        ],
        "description": "Form 8-K - Item 2.02",
        "linkToFilingDetails": (
            "https://www.sec.gov/Archives/edgar/data/1821769/report.htm"
        ),
        "documentFormatFiles": [
            {
                "type": "8-K",
                "description": "FORM 8-K",
                "documentUrl": (
                    "https://www.sec.gov/Archives/edgar/data/1821769/"
                    "report.htm"
                ),
                "sequence": "1",
            },
            {
                "type": "EX-99.1",
                "description": "PRESS RELEASE",
                "documentUrl": (
                    "https://www.sec.gov/Archives/edgar/data/1821769/"
                    "exhibit991.htm"
                ),
                "sequence": "2",
            },
        ],
    }
    result.update(changes)
    return result


class SecEarningsFilterTests(unittest.TestCase):
    def test_handshake_diagnostic_includes_only_http_status(self) -> None:
        class _Response:
            status_code = 401

        class _HandshakeFailure(RuntimeError):
            response = _Response()

        error = _HandshakeFailure(
            "sensitive response details must not be used"
        )

        self.assertEqual(
            _stream_error_code(error),
            "_HandshakeFailure:http_401",
        )

    def test_accepts_only_strict_initial_earnings_exhibit(self) -> None:
        decision = evaluate_sec_earnings_filing(
            _filing(),
            watch=_WATCH,
            received_at=_NOW,
        )

        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reason, "official_earnings_exhibit")
        candidate = decision.candidate
        assert candidate is not None
        self.assertEqual(candidate.scope_id, _WATCH.scope_id)
        self.assertEqual(candidate.ticker, "NVTS")
        self.assertEqual(candidate.cik, "1821769")
        self.assertEqual(candidate.document_type, "EX-99.1")
        self.assertEqual(candidate.filed_at.hour, 21)
        self.assertEqual(
            candidate.source_url,
            (
                "https://www.sec.gov/Archives/edgar/data/1821769/"
                "exhibit991.htm"
            ),
        )

    def test_rejects_non_initial_forms_and_missing_item(self) -> None:
        cases = (
            (_filing(formType="10-Q"), "not_initial_8k"),
            (_filing(formType="8-K/A"), "not_initial_8k"),
            (
                _filing(items=["Item 9.01"], description="Form 8-K"),
                "item_202_missing",
            ),
        )
        for filing, expected in cases:
            with self.subTest(expected=expected):
                decision = evaluate_sec_earnings_filing(
                    filing,
                    watch=_WATCH,
                    received_at=_NOW,
                )
                self.assertFalse(decision.accepted)
                self.assertEqual(decision.reason, expected)

    def test_rejects_issuer_mismatch_and_ambiguous_exhibits(self) -> None:
        mismatch = evaluate_sec_earnings_filing(
            _filing(cik="999"),
            watch=_WATCH,
            received_at=_NOW,
        )
        self.assertEqual(mismatch.reason, "cik_mismatch")

        filing = _filing()
        exhibits = list(filing["documentFormatFiles"])
        exhibits.append(
            {
                "type": "EX-99.1",
                "description": "EARNINGS RELEASE",
                "documentUrl": "https://www.sec.gov/second-exhibit.htm",
                "sequence": "3",
            }
        )
        ambiguous = evaluate_sec_earnings_filing(
            _filing(documentFormatFiles=exhibits),
            watch=_WATCH,
            received_at=_NOW,
        )
        self.assertEqual(ambiguous.reason, "exhibit_991_ambiguous")

    def test_requires_cik_but_not_a_descriptive_exhibit_label(self) -> None:
        missing_cik = evaluate_sec_earnings_filing(
            _filing(cik=None),
            watch=_WATCH,
            received_at=_NOW,
        )
        self.assertEqual(missing_cik.reason, "cik_missing")

        filing = _filing()
        exhibits = list(filing["documentFormatFiles"])
        exhibits[1] = {
            **exhibits[1],
            "description": "EXHIBIT 99.1",
        }
        accepted = evaluate_sec_earnings_filing(
            _filing(documentFormatFiles=exhibits),
            watch=_WATCH,
            received_at=_NOW,
        )
        self.assertTrue(accepted.accepted)

    def test_decodes_only_json_arrays_of_objects(self) -> None:
        self.assertEqual(
            decode_sec_stream_message(json.dumps([_filing()])),
            (_filing(),),
        )
        with self.assertRaisesRegex(
            SecStreamTransportError,
            "JSON array",
        ):
            decode_sec_stream_message("{}")
        with self.assertRaisesRegex(
            SecStreamTransportError,
            "only objects",
        ):
            decode_sec_stream_message("[1]")


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
    def __init__(
        self,
        *,
        socket: _FakeSocket | None = None,
        error: Exception | None = None,
    ):
        self._socket = socket
        self._error = error

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        assert self._socket is not None
        return self._socket

    async def __aexit__(self, *_: object) -> None:
        return None


class SecEarningsTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_emits_only_accepted_candidate(self) -> None:
        messages = [
            json.dumps(
                [
                    _filing(formType="10-Q"),
                    _filing(),
                ]
            )
        ]

        def connect(_uri: str, **_kwargs: object) -> _FakeConnection:
            return _FakeConnection(socket=_FakeSocket(messages))

        transport = SecStreamEarningsTransport(
            api_key="test-credential",
            watches=[_WATCH],
            connect_factory=connect,
            clock=lambda: _NOW,
        )
        found = [
            candidate
            async for candidate in transport.stream_once()
        ]

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].scope_id, _WATCH.scope_id)
        self.assertNotIn("test-credential", repr(transport))

    async def test_connection_error_cannot_echo_credential(self) -> None:
        credential = "credential-that-must-not-leak"

        def connect(uri: str, **_kwargs: object) -> _FakeConnection:
            return _FakeConnection(
                error=RuntimeError(f"connection failed for {uri}")
            )

        transport = SecStreamEarningsTransport(
            api_key=credential,
            watches=[_WATCH],
            connect_factory=connect,
            clock=lambda: _NOW,
        )

        with self.assertRaises(SecStreamTransportError) as caught:
            async for _ in transport.stream_once():
                pass

        self.assertNotIn(credential, str(caught.exception))
        self.assertNotIn(credential, repr(transport))
        self.assertEqual(
            caught.exception.diagnostic_code,
            "RuntimeError",
        )


if __name__ == "__main__":
    unittest.main()
