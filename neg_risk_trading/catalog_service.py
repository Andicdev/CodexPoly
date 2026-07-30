from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from neg_risk_trading.catalog_repository import (
    CatalogRepositoryError,
    SqlAlchemyCatalogRepository,
    utc_now,
)
from neg_risk_trading.polymarket import (
    PolymarketPublicClient,
    PublicApiError,
)
from neg_risk_trading.settings import NegRiskCatalogSettings


@dataclass(frozen=True)
class CatalogScanResult:
    page_count: int
    gamma_market_count: int
    neg_risk_market_count: int
    stored_market_count: int
    event_count: int
    issue_count: int
    skipped_market_count: int
    duration_ms: int


class ContinuousCatalogScanner:
    def __init__(
        self,
        *,
        settings: NegRiskCatalogSettings,
        repository: SqlAlchemyCatalogRepository | None = None,
        public_client: PolymarketPublicClient | None = None,
        logger: logging.Logger | None = None,
    ):
        self._settings = settings
        self._repository = repository or (
            SqlAlchemyCatalogRepository(settings.database_url)
        )
        self._public_client = public_client or PolymarketPublicClient(
            connect_timeout=settings.connect_timeout_seconds,
            read_timeout=settings.read_timeout_seconds,
            maximum_response_bytes=(
                settings.maximum_response_bytes
            ),
        )
        self._logger = logger or logging.getLogger(__name__)

    def run_once(self) -> CatalogScanResult:
        self._repository.ensure_ready()
        started_at = utc_now()
        started_ns = time.perf_counter_ns()
        scan_id = self._repository.start_scan(
            started_at=started_at,
            metadata={
                "source": "gamma_markets_keyset",
                "page_size": self._settings.page_size,
                "maximum_pages": self._settings.maximum_pages,
                "maximum_markets": (
                    self._settings.maximum_markets
                ),
                "classification": (
                    "metadata_screening_not_trading_signal"
                ),
            },
        )
        cursor: str | None = None
        seen_cursors: set[str] = set()
        event_ids: set[str] = set()
        page_count = 0
        gamma_market_count = 0
        neg_risk_market_count = 0
        stored_market_count = 0
        issue_count = 0
        skipped_market_count = 0
        try:
            while True:
                if page_count >= self._settings.maximum_pages:
                    raise PublicApiError(
                        "gamma_catalog_page_limit_exceeded"
                    )
                page = self._public_client.fetch_catalog_page(
                    after_cursor=cursor,
                    page_size=self._settings.page_size,
                )
                page_count += 1
                gamma_market_count += page.gamma_market_count
                neg_risk_market_count += (
                    page.neg_risk_market_count
                )
                stored_market_count += len(page.markets)
                issue_count += page.issue_count
                skipped_market_count += (
                    page.skipped_market_count
                )
                event_ids.update(
                    event.event_id
                    for event in page.events
                )
                if (
                    gamma_market_count
                    > self._settings.maximum_markets
                ):
                    raise PublicApiError(
                        "gamma_catalog_market_limit_exceeded"
                    )
                self._repository.record_page(
                    scan_id=scan_id,
                    page=page,
                    observed_at=utc_now(),
                )
                next_cursor = page.next_cursor
                if next_cursor is None:
                    break
                if not page.gamma_market_count:
                    raise PublicApiError(
                        "gamma_catalog_empty_page_with_cursor"
                    )
                if next_cursor in seen_cursors:
                    raise PublicApiError(
                        "gamma_catalog_cursor_repeated"
                    )
                seen_cursors.add(next_cursor)
                cursor = next_cursor

            completed_at = utc_now()
            duration_ms = (
                time.perf_counter_ns() - started_ns
            ) // 1_000_000
            self._repository.complete_scan(
                scan_id=scan_id,
                completed_at=completed_at,
                duration_ms=int(duration_ms),
            )
            return CatalogScanResult(
                page_count=page_count,
                gamma_market_count=gamma_market_count,
                neg_risk_market_count=neg_risk_market_count,
                stored_market_count=stored_market_count,
                event_count=len(event_ids),
                issue_count=issue_count,
                skipped_market_count=skipped_market_count,
                duration_ms=int(duration_ms),
            )
        except Exception as exc:
            duration_ms = (
                time.perf_counter_ns() - started_ns
            ) // 1_000_000
            try:
                self._repository.fail_scan(
                    scan_id=scan_id,
                    completed_at=utc_now(),
                    duration_ms=int(duration_ms),
                    reason_code=_reason_code(exc),
                )
            except CatalogRepositoryError:
                pass
            raise

    def run_forever(self) -> None:
        try:
            while True:
                try:
                    result = self.run_once()
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    self._logger.warning(
                        "Neg-risk catalog scan failed "
                        "reason=%s retry_seconds=%.3f",
                        _reason_code(exc),
                        self._settings.retry_interval_seconds,
                    )
                    time.sleep(
                        self._settings.retry_interval_seconds
                    )
                    continue
                self._logger.info(
                    "Neg-risk catalog scan complete "
                    "pages=%s gamma_markets=%s "
                    "neg_risk_markets=%s stored_markets=%s "
                    "events=%s issues=%s skipped_markets=%s "
                    "duration_ms=%s "
                    "live_orders_enabled=false",
                    result.page_count,
                    result.gamma_market_count,
                    result.neg_risk_market_count,
                    result.stored_market_count,
                    result.event_count,
                    result.issue_count,
                    result.skipped_market_count,
                    result.duration_ms,
                )
                time.sleep(self._settings.poll_interval_seconds)
        finally:
            self._repository.close()


def _reason_code(exc: Any) -> str:
    candidate = getattr(exc, "reason_code", None)
    reason = str(candidate or type(exc).__name__).strip()
    return reason[:160] or "catalog_scan_failed"
