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
from cbr_trading.earnings.parsers.navitas import (
    NavitasEpsParser,
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.secret_guard import redact_exception


_REPLAYS = (
    {
        "year": 2026,
        "quarter": 1,
        "period_end": date(2026, 3, 31),
        "expected": Decimal("-0.04"),
        "url": (
            "https://ir.navitassemi.com/news-releases/"
            "news-release-details/navitas-semiconductor-announces-"
            "first-quarter-2026-financial"
        ),
    },
    {
        "year": 2025,
        "quarter": 4,
        "period_end": date(2025, 12, 31),
        "expected": Decimal("-0.05"),
        "url": (
            "https://ir.navitassemi.com/news-releases/"
            "news-release-details/navitas-semiconductor-announces-"
            "fourth-quarter-and-full-year-0"
        ),
    },
    {
        "year": 2025,
        "quarter": 3,
        "period_end": date(2025, 9, 30),
        "expected": Decimal("-0.05"),
        "url": (
            "https://ir.navitassemi.com/news-releases/"
            "news-release-details/navitas-semiconductor-announces-"
            "third-quarter-2025-financial"
        ),
    },
    {
        "year": 2025,
        "quarter": 2,
        "period_end": date(2025, 6, 30),
        "expected": Decimal("-0.05"),
        "url": (
            "https://ir.navitassemi.com/news-releases/"
            "news-release-details/navitas-semiconductor-announces-"
            "second-quarter-2025-financial"
        ),
    },
)


def main() -> int:
    parser = NavitasEpsParser()
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
            rule = _replay_rule(replay)
            parsed = parser.parse(
                document,
                source=_source(rule, replay["url"]),
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
                    "period": (
                        f"{replay['year']}Q{replay['quarter']}"
                    ),
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


def _replay_rule(replay: dict[str, Any]):
    base = nvts_q2_2026_shadow_rule()
    year = int(replay["year"])
    quarter = int(replay["quarter"])
    return replace(
        base,
        rule_key=f"nvts-{year}q{quarter}-historical-replay",
        scope_id=earnings_scope_id("NVTS", year, quarter),
        fiscal_year=year,
        fiscal_quarter=quarter,
        period_end=replay["period_end"],
    )


def _source(rule: Any, url: str) -> EarningsDocumentCandidate:
    now = datetime.now(timezone.utc)
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.COMPANY_IR,
        provider_event_id=f"ir:{rule.scope_id}",
        ticker=rule.ticker,
        cik=rule.cik,
        form_type="IR",
        items=(),
        document_type="EARNINGS_RELEASE",
        source_url=url,
        filing_url=url,
        filed_at=now,
        received_at=now,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint=f"historical:{rule.scope_id}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
