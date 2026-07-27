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
from cbr_trading.earnings.parsers.july_28_sec import (
    HiltonAdjustedDilutedEpsParser,
    hlt_q2_2026_shadow_rule,
)
from cbr_trading.secret_guard import redact_exception


_URL = (
    "https://stories.hilton.com/releases/"
    "hilton-reports-2026-first-quarter-results"
)
_MAX_DOCUMENT_BYTES = 8 * 1024 * 1024


def main() -> int:
    try:
        request = Request(
            _URL,
            headers={
                "User-Agent": (
                    "CodexPoly earnings-source historical verification"
                )
            },
        )
        with urlopen(request, timeout=20) as response:
            document = response.read(_MAX_DOCUMENT_BYTES + 1)
        if len(document) > _MAX_DOCUMENT_BYTES:
            raise ValueError("Hilton replay document exceeds size limit")

        rule = replace(
            hlt_q2_2026_shadow_rule(),
            rule_key="hlt-2026q1-historical-replay",
            scope_id=earnings_scope_id("HLT", 2026, 1),
            fiscal_quarter=1,
            period_end=date(2026, 3, 31),
        )
        detected_at = datetime.now(timezone.utc)
        parsed = HiltonAdjustedDilutedEpsParser().parse(
            document,
            source=EarningsDocumentCandidate(
                scope_id=rule.scope_id,
                provider=EarningsProvider.COMPANY_IR,
                provider_event_id="company_ir:HLT:2026Q1",
                ticker=rule.ticker,
                cik=rule.cik,
                form_type="PRESS_RELEASE",
                items=(),
                document_type="HTML",
                source_url=_URL,
                filing_url=_URL,
                filed_at=detected_at,
                received_at=detected_at,
                authority=SourceAuthority.OFFICIAL_COMPANY,
                transport_fingerprint="historical:HLT:2026Q1",
            ),
            rule=rule,
            detected_at=detected_at,
        )
        value = (
            parsed.candidate.value
            if parsed.candidate is not None
            else None
        )
        ok = (
            parsed.status is ParseStatus.ACCEPTED
            and value == Decimal("2.01")
        )
        payload = {
            "ok": ok,
            "provider": EarningsProvider.COMPANY_IR.value,
            "period": "2026Q1",
            "status": parsed.status.value,
            "reason": parsed.reason,
            "value": str(value) if value is not None else None,
            "expected": "2.01",
            "url": _URL,
        }
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": redact_exception(exc),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 5

    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=sys.stdout if ok else sys.stderr,
    )
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
