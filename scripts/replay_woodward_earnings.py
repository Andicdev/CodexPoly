from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.request import Request, urlopen

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    ParseStatus,
    SourceAuthority,
    earnings_scope_id,
)
from cbr_trading.earnings.parsers.woodward import (
    WoodwardGaapEpsParser,
    wwd_q3_2026_shadow_rule,
)
from cbr_trading.secret_guard import redact_exception


_REPLAYS = (
    {
        "provider": EarningsProvider.COMPANY_IR,
        "expected": Decimal("2.19"),
        "url": (
            "https://www.woodward.com/press-release/"
            "woodward-reports-second-quarter-fiscal-year-2026-results/"
        ),
    },
    {
        "provider": EarningsProvider.GLOBE_NEWSWIRE,
        "expected": Decimal("2.19"),
        "url": (
            "https://www.globenewswire.com/news-release/2026/04/29/"
            "3284205/0/en/Woodward-Reports-Second-Quarter-Fiscal-"
            "Year-2026-Results.html"
        ),
    },
)


def main() -> int:
    parser = WoodwardGaapEpsParser()
    results: list[dict[str, Any]] = []
    try:
        for replay in _REPLAYS:
            request = Request(
                replay["url"],
                headers={
                    "User-Agent": (
                        "CodexPoly earnings-source historical verification"
                    )
                },
            )
            with urlopen(request, timeout=20) as response:
                document = response.read()
            rule = _replay_rule()
            parsed = parser.parse(
                document,
                source=_source(
                    rule,
                    replay["url"],
                    replay["provider"],
                ),
                rule=rule,
                detected_at=datetime.now(timezone.utc),
            )
            value = (
                parsed.candidate.value
                if parsed.candidate is not None
                else None
            )
            ok = (
                parsed.status is ParseStatus.ACCEPTED
                and value == replay["expected"]
            )
            results.append(
                {
                    "period": "2026Q2",
                    "provider": replay["provider"].value,
                    "ok": ok,
                    "status": parsed.status.value,
                    "reason": parsed.reason,
                    "value": str(value) if value is not None else None,
                    "expected": str(replay["expected"]),
                    "url": replay["url"],
                }
            )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": redact_exception(exc),
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 5

    payload = {
        "ok": all(item["ok"] for item in results),
        "results": results,
    }
    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=sys.stdout if payload["ok"] else sys.stderr,
    )
    return 0 if payload["ok"] else 5


def _replay_rule():
    return replace(
        wwd_q3_2026_shadow_rule(),
        rule_key="wwd-2026q2-historical-replay",
        scope_id=earnings_scope_id("WWD", 2026, 2),
        fiscal_quarter=2,
        period_end=date(2026, 3, 31),
    )


def _source(
    rule: Any,
    url: str,
    provider: EarningsProvider,
) -> EarningsDocumentCandidate:
    now = datetime.now(timezone.utc)
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=provider,
        provider_event_id=f"{provider.value}:{rule.scope_id}",
        ticker=rule.ticker,
        cik=rule.cik,
        form_type="PRESS_RELEASE",
        items=(),
        document_type="HTML",
        source_url=url,
        filing_url=url,
        filed_at=now,
        received_at=now,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint=f"historical:{rule.scope_id}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
