# common/ingest_utils.py
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from typing import Optional
from sqlalchemy import select, func, update
from sqlalchemy.dialects.postgresql import insert

from common.db import get_session

from models.t_companies import Company
from models.t_company_doc_watch import CompanyDocWatch
from models.t_ingested_docs import IngestedDoc


PrimarySession = get_session("primary")


def _norm_ticker(ticker: str | None) -> str | None:
    if not ticker:
        return None
    t = ticker.strip().upper()
    return t or None


def _norm_cik(cik: str | None) -> str | None:
    if not cik:
        return None
    c = str(cik).strip()
    # SEC CIK часто бывает с лидирующими нулями — оставим как строку
    return c or None


def compute_dedup_key(
    *,
    source: str,
    doc_type: str,
    url: str,
    published_at: datetime | None,
    ticker: str | None,
    cik: str | None,
    extra: dict[str, Any] | None = None,
) -> str:
    """
    Стабильный ключ дедупликации (sha256).
    Важно: одинаковые события из разных источников могут иметь разные URL,
    поэтому при желании можно класть сюда ещё accessionNo / filingId и т.п. через extra.
    """
    obj = {
        "source": (source or "").strip().lower(),
        "doc_type": (doc_type or "").strip().upper(),
        "url": (url or "").strip(),
        "published_at": (published_at.isoformat() if published_at else None),
        "ticker": _norm_ticker(ticker),
        "cik": _norm_cik(cik),
        "extra": (extra or {}),
    }
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class WatchDecision:
    allowed: bool
    company_id: int | None = None
    ticker: str | None = None
    cik: str | None = None
    reason: str | None = None


class CompanyWatchCache:
    """
    Кеш “что мониторим”, чтобы не бить БД на каждое событие.
    Перезагрузка раз в ttl_sec.
    """

    def __init__(self, *, ttl_sec: int = 30):
        self.ttl_sec = int(ttl_sec)
        self._loaded_at = 0.0

        # maps
        self._ticker_to_company: dict[str, tuple[int, str | None]] = {}
        self._cik_to_company: dict[str, tuple[int, str | None]] = {}
        self._watch_set: set[tuple[int, str, str]] = set()  # (company_id, doc_type, source)

    def maybe_reload(self) -> None:
        now = time.time()
        if (now - self._loaded_at) < self.ttl_sec and self._loaded_at > 0:
            return

        with PrimarySession() as s:
            companies = s.execute(
                select(Company.id, Company.ticker, Company.cik)
                .where(Company.enabled.is_(True))
            ).all()

            self._ticker_to_company.clear()
            self._cik_to_company.clear()
            for cid, t, cik in companies:
                tt = _norm_ticker(t)
                if tt:
                    self._ticker_to_company[tt] = (int(cid), _norm_cik(cik))
                cc = _norm_cik(cik)
                if cc:
                    self._cik_to_company[cc] = (int(cid), _norm_ticker(t))

            watches = s.execute(
                select(CompanyDocWatch.company_id, CompanyDocWatch.doc_type, CompanyDocWatch.source)
                .where(CompanyDocWatch.enabled.is_(True))
            ).all()
            self._watch_set = {(int(cid), str(dt).upper(), str(src).lower()) for cid, dt, src in watches}

        self._loaded_at = now

    def resolve_company(self, *, ticker: str | None, cik: str | None) -> tuple[int | None, str | None, str | None]:
        self.maybe_reload()
        tt = _norm_ticker(ticker)
        cc = _norm_cik(cik)

        if tt and tt in self._ticker_to_company:
            cid, cik2 = self._ticker_to_company[tt]
            return cid, tt, (cik2 or cc)

        if cc and cc in self._cik_to_company:
            cid, ticker2 = self._cik_to_company[cc]
            return cid, (ticker2 or tt), cc

        return None, tt, cc

    def is_watched(self, *, company_id: int, doc_type: str, source: str) -> bool:
        self.maybe_reload()
        return (int(company_id), str(doc_type).upper(), str(source).lower()) in self._watch_set


def check_watch(
    *,
    cache: CompanyWatchCache,
    ticker: str | None,
    cik: str | None,
    source: str,
    doc_type: str,
) -> WatchDecision:
    company_id, tt, cc = cache.resolve_company(ticker=ticker, cik=cik)
    if not company_id:
        return WatchDecision(False, None, tt, cc, "company_not_found_or_disabled")

    if not cache.is_watched(company_id=company_id, doc_type=doc_type, source=source):
        return WatchDecision(False, company_id, tt, cc, "doc_type_or_source_not_watched")

    return WatchDecision(True, company_id, tt, cc, None)


def upsert_ingested_doc(
    *,
    company_id: int,
    ticker: str,
    cik: str | None,
    source: str,
    doc_type: str,
    url: str,
    published_at: datetime | None,
    dedup_key: str,
    payload: dict[str, Any] | None = None,
    status: str = "NEW",
) -> int:
    """
    Upsert по dedup_key. Возвращает ingested_docs.id.
    payload при конфликте мерджится JSONB-оператором || (новое поверх старого).
    """
    payload = payload or {}

    with PrimarySession() as s:
        stmt = insert(IngestedDoc).values(
            company_id=int(company_id),
            ticker=_norm_ticker(ticker) or ticker,
            cik=_norm_cik(cik),
            source=str(source).lower(),
            doc_type=str(doc_type).upper(),
            url=str(url),
            published_at=published_at,
            dedup_key=str(dedup_key),
            payload=payload,
            status=status,
            updated_at=func.now(),
        )

        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=[IngestedDoc.dedup_key],
            set_={
                "updated_at": func.now(),
                "payload": IngestedDoc.payload.op("||")(excluded.payload),
                # статус НЕ перетираем “DONE/ERROR”, но NEW можно освежить (по желанию)
                # "status": excluded.status,
            },
        ).returning(IngestedDoc.id)

        ing_id = s.execute(stmt).scalar_one()
        s.commit()
        return int(ing_id)

def upsert_ingested_doc_ex(
    *,
    company_id: int,
    ticker: str,
    cik: str | None,
    source: str,
    doc_type: str,
    url: str,
    published_at: datetime | None,
    dedup_key: str,
    payload: dict[str, Any] | None = None,
    status: str = "NEW",
) -> tuple[int, bool]:
    """
    Совместимый расширенный upsert.
    Возвращает (ingested_docs.id, inserted_flag).

    inserted_flag=True  -> была новая вставка
    inserted_flag=False -> сработал dedup/update существующей строки
    """
    payload = payload or {}

    with PrimarySession() as s:
        insert_stmt = insert(IngestedDoc).values(
            company_id=int(company_id),
            ticker=_norm_ticker(ticker) or ticker,
            cik=_norm_cik(cik),
            source=str(source).lower(),
            doc_type=str(doc_type).upper(),
            url=str(url),
            published_at=published_at,
            dedup_key=str(dedup_key),
            payload=payload,
            status=status,
            updated_at=func.now(),
        )

        inserted_id = s.execute(
            insert_stmt.on_conflict_do_nothing(
                index_elements=[IngestedDoc.dedup_key],
            ).returning(IngestedDoc.id)
        ).scalar_one_or_none()

        if inserted_id is not None:
            s.commit()
            return int(inserted_id), True

        update_stmt = (
            update(IngestedDoc)
            .where(IngestedDoc.dedup_key == str(dedup_key))
            .values(
                updated_at=func.now(),
                payload=IngestedDoc.payload.op("||")(payload),
            )
            .returning(IngestedDoc.id)
        )
        ing_id = s.execute(update_stmt).scalar_one()
        s.commit()
        return int(ing_id), False

def ingest_event(
    *,
    cache: CompanyWatchCache,
    ticker: str | None,
    cik: str | None,
    source: str,
    doc_type: str,
    url: str,
    published_at: datetime | None,
    payload: dict[str, Any] | None = None,
    extra_dedup: dict[str, Any] | None = None,
) -> tuple[bool, int | None, str]:
    """
    Главная точка входа для ингестеров.
    Возвращает (inserted_or_updated, ingest_id, reason)
    """
    dec = check_watch(cache=cache, ticker=ticker, cik=cik, source=source, doc_type=doc_type)
    if not dec.allowed:
        return False, None, dec.reason or "not_allowed"

    # SEC 8-K: prefer URL-based dedup so the same filing URL coming from different
    # ingesters (socket vs polling) doesn't create duplicate ingested_docs rows.
    # This keeps Scheme A stable: url is the identity of the document.
    if str(source).lower() == "sec" and str(doc_type).upper() == "SEC_8K":
        obj = {
            "source": str(source).lower(),
            "doc_type": str(doc_type).upper(),
            "url": (url or "").strip(),
        }
        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        dedup_key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        reason_updated = "ok_url_dedup"
    else:
        dedup_key = compute_dedup_key(
            source=source,
            doc_type=doc_type,
            url=url,
            published_at=published_at,
            ticker=dec.ticker,
            cik=dec.cik,
            extra=extra_dedup,
        )
        reason_updated = "ok"

    ing_id, inserted = upsert_ingested_doc_ex(
        company_id=int(dec.company_id),
        ticker=dec.ticker or (ticker or ""),
        cik=dec.cik,
        source=source,
        doc_type=doc_type,
        url=url,
        published_at=published_at,
        dedup_key=dedup_key,
        payload=payload,
        status="NEW",
    )
    return True, ing_id, ("inserted" if inserted else reason_updated)