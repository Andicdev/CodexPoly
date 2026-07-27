from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.request import Request, urlopen

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    ParseStatus,
    SourceAuthority,
    earnings_scope_id,
)
from cbr_trading.earnings.parsers.boeing import (
    BOEING_CIK,
    BoeingCoreEpsParser,
    ba_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers._common import (
    decode_document,
    document_text,
)
from cbr_trading.secret_guard import redact_exception


_URL = (
    "https://www.prnewswire.com/news-releases/"
    "boeing-reports-second-quarter-results-302516005.html"
)
_EXPECTED = Decimal("-1.24")


def main() -> int:
    try:
        request = Request(
            _URL,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": (
                    "CodexPoly earnings-source historical verification"
                ),
            },
            method="GET",
        )
        with urlopen(request, timeout=30) as response:
            document = response.read(8 * 1024 * 1024 + 1)
        if not document or len(document) > 8 * 1024 * 1024:
            raise RuntimeError("historical document size is invalid")

        rule = replace(
            ba_q2_2026_shadow_rule(),
            rule_key="ba-2025q2-prnewswire-historical-replay",
            scope_id=earnings_scope_id("BA", 2025, 2),
            fiscal_year=2025,
            fiscal_quarter=2,
            period_end=date(2025, 6, 30),
        )
        now = datetime.now(timezone.utc)
        boeing_parser = BoeingCoreEpsParser()
        parsed = boeing_parser.parse(
            document,
            source=EarningsDocumentCandidate(
                scope_id=rule.scope_id,
                provider=EarningsProvider.PR_NEWSWIRE,
                provider_event_id="prnewswire:302516005",
                ticker=rule.ticker,
                cik=BOEING_CIK,
                form_type="PRESS_RELEASE",
                items=(),
                document_type="HTML",
                source_url=_URL,
                filing_url=_URL,
                filed_at=now,
                received_at=now,
                authority=SourceAuthority.OFFICIAL_COMPANY,
                transport_fingerprint=(
                    "historical:ba:2025q2:prnewswire"
                ),
            ),
            rule=rule,
            detected_at=now,
        )
        observed_values = sorted(
            {
                str(item[0])
                for item in boeing_parser._extract_values(
                    document_text(decode_document(document))
                )
            }
        )
        value = (
            parsed.candidate.value
            if parsed.candidate is not None
            else None
        )
        ok = (
            parsed.status is ParseStatus.ACCEPTED
            and value == _EXPECTED
        )
        payload = {
            "ok": ok,
            "provider": EarningsProvider.PR_NEWSWIRE.value,
            "period": "2025Q2",
            "status": parsed.status.value,
            "reason": parsed.reason,
            "value": str(value) if value is not None else None,
            "expected": str(_EXPECTED),
            "observed_values": observed_values,
            "url": _URL,
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "error": redact_exception(exc),
        }

    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=sys.stdout if payload["ok"] else sys.stderr,
    )
    return 0 if payload["ok"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
