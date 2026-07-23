from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
from dotenv import load_dotenv
from sqlalchemy import func, update

from common.db import get_session
from common.ingest_utils import CompanyWatchCache, ingest_event
from common.logger import get_logger

from models.t_extracted_values import ExtractedValue
from models.t_ingested_docs import IngestedDoc
from news_trade.central_bank_policy_history import upsert_policy_decision
from news_trade.extract_eps_from_ingest_worker import load_ingested_doc_for_fast_path
from news_trade.trade_from_extracted_values_worker import process_extracted_value

logger = get_logger(__name__)
WATCH_CACHE = CompanyWatchCache(ttl_sec=30)
PrimarySession = get_session("primary")

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/133.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
    }
)

DEFAULT_REPLAY_URL = "https://cbr.ru/eng/press/pr/?file=13022026_133000key_e.htm"

_CBR_PREV_RATE_CACHE: float | None = None
_CBR_PREV_RATE_SOURCE: str | None = None


def _clean_env_value(v: str | None) -> str:
    s = str(v or "").strip()
    s = s.rstrip("\\").strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        s = s[1:-1].strip()
    return s


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d.%m.%Y",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return None


def _append_cache_buster(url: str) -> str:
    if str(os.getenv("BOR_DISABLE_CACHE_BUSTER", "0")).strip().lower() in ("1", "true", "yes"):
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}_ts={int(time.time() * 1000)}"


def _build_predicted_release_url(for_date: datetime | None = None) -> str:
    dt = for_date or datetime.now(timezone.utc)
    raw = _clean_env_value(os.getenv("BOR_RELEASE_DATE") or "")
    if raw:
        parsed = _parse_dt(raw)
        if parsed is not None:
            dt = parsed
    ddmmyyyy = dt.strftime("%d%m%Y")
    suffix = _clean_env_value(os.getenv("BOR_RELEASE_TIME_SUFFIX") or "133000key_e")
    return f"https://cbr.ru/eng/press/pr/?file={ddmmyyyy}_{suffix}.htm"


def _html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", s)
    s = re.sub(r"(?is)<br\\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p\\s*>", "\n", s)
    s = re.sub(r"(?is)</div\\s*>", "\n", s)
    s = re.sub(r"(?is)</li\\s*>", "\n", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s+", "\n", s)
    return s.strip()


def _compact_text(text: str) -> str:
    return " ".join((text or "").split())


def _fetch_url(
    url: str,
    timeout: float | tuple[float, float] | None = None,
    *,
    cache_bust: bool = False,
) -> dict[str, Any]:
    if timeout is None:
        timeout = float(os.getenv("BOR_FETCH_TIMEOUT_SEC", "5"))
    req_url = _append_cache_buster(url) if cache_bust else url
    r = SESSION.get(req_url, timeout=timeout)
    r.raise_for_status()
    return {
        "url": url,
        "request_url": req_url,
        "status_code": r.status_code,
        "content_type": (r.headers.get("content-type") or "").lower(),
        "text": r.text,
    }


def _fetch_prefix(url: str, *, cache_bust: bool = False) -> dict[str, Any]:
    connect_timeout = float(os.getenv("BOR_CONNECT_TIMEOUT_SEC", "0.5"))
    read_timeout = float(os.getenv("BOR_READ_TIMEOUT_SEC", "0.5"))
    max_bytes = int(os.getenv("BOR_PREFIX_MAX_BYTES", "32768"))
    chunk_size = int(os.getenv("BOR_PREFIX_CHUNK_SIZE", "2048"))
    req_url = _append_cache_buster(url) if cache_bust else url

    try:
        with SESSION.get(req_url, timeout=(connect_timeout, read_timeout), stream=True) as r:
            status_code = r.status_code
            content_type = (r.headers.get("content-type") or "").lower()
            if status_code == 404:
                return {
                    "url": url,
                    "request_url": req_url,
                    "status_code": status_code,
                    "content_type": content_type,
                    "text": "",
                }
            if status_code == 403:
                raise requests.HTTPError("403 from stream fetch", response=r)
            r.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in r.iter_content(chunk_size=chunk_size, decode_unicode=False):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total >= max_bytes:
                    break
            enc = r.encoding or r.apparent_encoding or "utf-8"
            text = b"".join(chunks).decode(enc, errors="ignore")
            return {
                "url": url,
                "request_url": req_url,
                "status_code": status_code,
                "content_type": content_type,
                "text": text,
            }
    except requests.RequestException:
        r = SESSION.get(req_url, timeout=max(connect_timeout + read_timeout, 3.0), stream=False)
        status_code = r.status_code
        content_type = (r.headers.get("content-type") or "").lower()
        if status_code == 404:
            return {
                "url": url,
                "request_url": req_url,
                "status_code": status_code,
                "content_type": content_type,
                "text": "",
            }
        r.raise_for_status()
        text = (r.text or "")[:max_bytes]
        return {
            "url": url,
            "request_url": req_url,
            "status_code": status_code,
            "content_type": content_type,
            "text": text,
        }


def _extract_title(html: str) -> str:
    m = re.search(r"(?is)<title>(.*?)</title>", html or "")
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _parse_release_rate_from_title(title: str) -> float | None:
    t = _compact_text(title)
    patterns = [
        r"\bkey rate\b[^.]{0,120}?\bto\s+(\d+(?:\.\d+)?)%\s*(?:p\.a\.|per annum)?",
        r"\bkey rate\b[^.]{0,120}?\bat\s+(\d+(?:\.\d+)?)%\s*(?:p\.a\.|per annum)?",
        r"\bkeeps the key rate at\s+(\d+(?:\.\d+)?)%",
        r"\bcuts the key rate by\s+\d+\s*bp\s+to\s+(\d+(?:\.\d+)?)%",
        r"\bcuts the key rate to\s+(\d+(?:\.\d+)?)%",
        r"\braises the key rate by\s+\d+\s*bp\s+to\s+(\d+(?:\.\d+)?)%",
        r"\braises the key rate to\s+(\d+(?:\.\d+)?)%",
        r"\bincreases the key rate to\s+(\d+(?:\.\d+)?)%",
        r"\blowers the key rate to\s+(\d+(?:\.\d+)?)%",
    ]
    for pat in patterns:
        m = re.search(pat, t, re.I)
        if not m:
            continue
        try:
            return float(m.group(1))
        except Exception:
            continue
    return None


def _parse_release_rate(text: str) -> float | None:
    source_text = _compact_text(text)
    patterns = [
        r"\bkey rate\b[^.]{0,120}?\bto\s+(\d+(?:\.\d+)?)%\s+per annum",
        r"\bkey rate\b[^.]{0,120}?\bat\s+(\d+(?:\.\d+)?)%\s+per annum",
        r"\bdecided to\s+(?:keep|maintain|retain)\b[^.]{0,160}?\b(?:at|to)\s+(\d+(?:\.\d+)?)%\s+per annum",
        r"\bdecided to\s+(?:cut|reduce|lower|raise|increase|hike)\b[^.]{0,160}?\bto\s+(\d+(?:\.\d+)?)%\s+per annum",
        r"\bkey rate\b[^0-9]{0,80}(\d+(?:\.\d+)?)%",
    ]
    for pat in patterns:
        m = re.search(pat, source_text, re.I)
        if not m:
            continue
        try:
            return float(m.group(1))
        except Exception:
            continue
    return None


def _looks_like_key_rate_release(text: str) -> bool:
    t = _compact_text(text)
    patterns = [
        r"\bkey rate\b",
        r"\bboard of directors\b[^.]{0,120}\bkey rate\b",
        r"\bdecided to\b[^.]{0,120}\bkey rate\b",
    ]
    return any(re.search(p, t, re.I) for p in patterns)


def _build_event_from_release_url(
    url: str,
    *,
    detected_from: str,
    published_at: str | None = None,
    cache_bust: bool = False,
) -> dict[str, Any]:
    prefix = _fetch_prefix(url, cache_bust=cache_bust)
    html_prefix = str(prefix.get("text") or "")
    title = _extract_title(html_prefix)
    new_rate = _parse_release_rate_from_title(title)

    use_body_fallback = str(os.getenv("BOR_FETCH_FULL_BODY_FALLBACK", "0")).strip().lower() in ("1", "true", "yes")
    raw_text = ""
    raw_preview = title[:4000]

    if new_rate is None and use_body_fallback:
        doc = _fetch_url(url, cache_bust=cache_bust)
        title = _extract_title(doc["text"]) or title
        raw_text = _html_to_text(doc["text"])
        raw_preview = (title + " | " + raw_text[:1000]).strip(" |")[:4000]
        new_rate = _parse_release_rate_from_title(title)
        if new_rate is None:
            new_rate = _parse_release_rate(raw_text)

    return {
        "ticker": "CBR",
        "sourceDoc": url,
        "publishedAt": published_at,
        "title": title,
        "detectedFrom": detected_from,
        "rawText": raw_text,
        "rawPreview": raw_preview,
        "new_rate": new_rate,
    }


def _discover_predicted_event() -> dict[str, Any]:
    predicted_url = _build_predicted_release_url()
    try:
        prefix = _fetch_prefix(predicted_url, cache_bust=True)
        status_code = int(prefix.get("status_code") or 0)
        title = _extract_title(prefix.get("text") or "")
        new_rate = _parse_release_rate_from_title(title)

        if status_code == 404:
            return {
                "ok": False,
                "reason": "not_published_yet",
                "ticker": "CBR",
                "url": predicted_url,
                "path": "predicted_url",
                "preview": "",
            }

        if new_rate is None or not _looks_like_key_rate_release(title):
            return {
                "ok": False,
                "reason": "not_published_yet",
                "ticker": "CBR",
                "url": predicted_url,
                "path": "predicted_url",
                "preview": title[:300],
            }

        return {
            "ok": True,
            "ticker": "CBR",
            "sourceDoc": predicted_url,
            "publishedAt": _clean_env_value(os.getenv("BOR_RELEASE_DATE") or "") or None,
            "title": title,
            "detectedFrom": "predicted_release_url",
            "rawText": "",
            "rawPreview": title[:4000],
            "new_rate": new_rate,
        }
    except Exception:
        logger.exception("CBR predicted release discovery failed url=%s", predicted_url)
        return {
            "ok": False,
            "reason": "fetch_failed",
            "ticker": "CBR",
            "url": predicted_url,
            "path": "predicted_url",
        }


def _discover_latest_event() -> dict[str, Any]:
    return _discover_predicted_event()


def _find_previous_rate(target_url: str, items: list[dict[str, Any]] | None = None) -> tuple[float | None, str | None]:
    logger.info("CBR previous-rate lookup disabled in release-only mode target_url=%s", target_url)
    return None, None


def _classify_change(prev_rate: float | None, new_rate: float | None) -> tuple[float | None, str | None]:
    if prev_rate is None or new_rate is None:
        return None, None
    change_bp = round((float(new_rate) - float(prev_rate)) * 100.0, 6)
    if change_bp < 0:
        return change_bp, "decrease"
    if change_bp > 0:
        return change_bp, "increase"
    return change_bp, "no_change"


def _get_prev_rate_from_cache_or_env() -> tuple[float | None, str | None]:
    global _CBR_PREV_RATE_CACHE, _CBR_PREV_RATE_SOURCE

    if _CBR_PREV_RATE_CACHE is not None:
        return _CBR_PREV_RATE_CACHE, _CBR_PREV_RATE_SOURCE or "memory_cache"

    raw = _clean_env_value(os.getenv("BOR_PREV_RATE") or "")
    if raw:
        try:
            _CBR_PREV_RATE_CACHE = float(raw)
            _CBR_PREV_RATE_SOURCE = "env:BOR_PREV_RATE"
            return _CBR_PREV_RATE_CACHE, _CBR_PREV_RATE_SOURCE
        except Exception:
            logger.exception("CBR invalid BOR_PREV_RATE=%r", raw)

    return None, None


def _set_prev_rate_cache(new_rate: float | None) -> None:
    global _CBR_PREV_RATE_CACHE, _CBR_PREV_RATE_SOURCE
    if new_rate is None:
        return
    try:
        _CBR_PREV_RATE_CACHE = float(new_rate)
        _CBR_PREV_RATE_SOURCE = "memory_from_current_release"
    except Exception:
        logger.exception("CBR failed to update prev-rate memory cache new_rate=%r", new_rate)


def _insert_extracted_value(
    *,
    company_id: int,
    ingest_id: int,
    ticker: str,
    metric_key: str,
    value_num: float | None,
    value_raw: str | None,
    confidence: float | None,
    evidence: dict[str, Any],
    resolver_name: str,
    resolver_ver: str,
) -> int:
    with PrimarySession() as s:
        obj = ExtractedValue(
            company_id=int(company_id),
            ingest_id=int(ingest_id),
            ticker=ticker,
            metric_key=metric_key,
            value_num=value_num,
            value_raw=value_raw,
            confidence=confidence,
            evidence=evidence,
            resolver_name=resolver_name,
            resolver_ver=resolver_ver,
            created_at=datetime.now(timezone.utc),
        )
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return int(obj.id)


def _set_status(ingest_id: int, status: str, error: str | None = None) -> None:
    with PrimarySession() as s:
        s.execute(
            update(IngestedDoc)
            .where(IngestedDoc.id == int(ingest_id))
            .values(status=status, error=error, updated_at=func.now())
        )
        s.commit()


def _write_metric_and_maybe_trade(
    *,
    company_id: int,
    ingest_id: int,
    ticker: str,
    metric_key: str,
    value_num: float | None,
    value_raw: str | None,
    confidence: float,
    evidence: dict[str, Any],
    trigger_trade: bool,
) -> int:
    ev_id = _insert_extracted_value(
        company_id=company_id,
        ingest_id=ingest_id,
        ticker=ticker,
        metric_key=metric_key,
        value_num=value_num,
        value_raw=value_raw,
        confidence=confidence,
        evidence=evidence,
        resolver_name="direct_ingest",
        resolver_ver="bank_of_russia_v2",
    )
    if trigger_trade:
        process_extracted_value(
            {
                "id": ev_id,
                "company_id": company_id,
                "ingest_id": ingest_id,
                "ticker": ticker,
                "metric_key": metric_key,
                "value_num": value_num,
                "value_raw": value_raw,
                "confidence": confidence,
                "evidence": evidence,
            },
            execution_path="fast",
            update_trade_status=False,
        )
    return ev_id


def handle_event(
    event: dict[str, Any],
    *,
    prev_rate_hint: float | None = None,
    prev_url_hint: str | None = None,
    prev_source: str | None = None,
    allow_previous_release_lookup: bool = True,
) -> dict[str, Any]:
    ticker = "CBR"
    url = str(event.get("sourceDoc") or event.get("url") or "").strip()
    title = str(event.get("title") or "").strip()
    published_at_raw = event.get("publishedAt")
    published_at = _parse_dt(str(published_at_raw)) if published_at_raw else None
    raw_text = str(event.get("rawText") or "")
    new_rate = event.get("new_rate")

    payload = {
        "ticker": ticker,
        "sourceDoc": url,
        "publishedAt": published_at_raw,
        "title": title,
        "detectedFrom": event.get("detectedFrom"),
        "rawText": raw_text,
        "rawPreview": event.get("rawPreview") or raw_text[:4000],
    }

    ok, ing_id, reason = ingest_event(
        cache=WATCH_CACHE,
        ticker=ticker,
        cik=None,
        source="cbr",
        doc_type="KEY_RATE_DECISION",
        url=url,
        published_at=published_at,
        payload=payload,
        extra_dedup={"title": title, "sourceDoc": url},
    )

    result = {
        "ok": ok,
        "ingest_id": ing_id,
        "reason": reason,
        "ticker": ticker,
        "url": url,
        "title": title,
        "new_rate": new_rate,
        "prev_rate": None,
        "prev_url": None,
        "change_bp": None,
        "direction": None,
        "tradable": False,
    }

    if not ok or not ing_id:
        return result

    if reason not in ("inserted", "updated"):
        return result

    try:
        row = load_ingested_doc_for_fast_path(int(ing_id))
        if not row:
            _set_status(int(ing_id), "ERROR", "fast-path load failed")
            result["reason"] = "fast_path_load_failed"
            result["ok"] = False
            return result

        company_id = int(row["company_id"])

        prev_rate = prev_rate_hint
        prev_url = prev_url_hint

        if prev_rate is None and allow_previous_release_lookup:
            prev_rate, prev_url = _find_previous_rate(url, None)

        change_bp, direction = _classify_change(prev_rate, new_rate)

        result.update({
            "prev_rate": prev_rate,
            "prev_url": prev_url,
            "prev_source": prev_source,
            "change_bp": change_bp,
            "direction": direction,
            "tradable": change_bp is not None,
        })

        evidence_base = {
            "url": url,
            "source": "cbr",
            "doc_type": "KEY_RATE_DECISION",
            "title": title,
            "publishedAt": published_at_raw,
            "detectedFrom": event.get("detectedFrom"),
            "new_rate": new_rate,
            "prev_rate": prev_rate,
            "prev_url": prev_url,
            "prev_source": prev_source,
            "change_bp": change_bp,
            "direction": direction,
            "rawPreview": (event.get("rawPreview") or "")[:4000],
        }

        decision_time_utc = published_at or datetime.now(timezone.utc)
        if new_rate is not None:
            policy_row = upsert_policy_decision(
                bank_code="CBR",
                instrument_code="KEY_RATE",
                decision_time_utc=decision_time_utc,
                target_value=float(new_rate),
                direction=str(direction) if direction is not None else None,
                source="cbr",
                source_doc_type="KEY_RATE_DECISION",
                source_url=url,
                ingest_id=int(ing_id),
                evidence={"kind": "direct_ingest_bank_of_russia", **evidence_base},
            )
            result["policy_change_bps"] = policy_row.get("change_bps")

        if new_rate is not None:
            _write_metric_and_maybe_trade(
                company_id=company_id,
                ingest_id=int(ing_id),
                ticker=ticker,
                metric_key="cbr_key_rate_target",
                value_num=float(new_rate),
                value_raw=str(new_rate),
                confidence=0.95,
                evidence={**evidence_base, "metric": "cbr_key_rate_target"},
                trigger_trade=False,
            )

        if change_bp is not None:
            _write_metric_and_maybe_trade(
                company_id=company_id,
                ingest_id=int(ing_id),
                ticker=ticker,
                metric_key="cbr_key_rate_change_bp",
                value_num=float(change_bp),
                value_raw=str(change_bp),
                confidence=0.95,
                evidence={
                    **evidence_base,
                    "metric": "cbr_key_rate_change_bp",
                    "reason": "change_from_previous_release" if allow_previous_release_lookup else "change_from_cached_prev_rate",
                },
                trigger_trade=True,
            )

        _set_prev_rate_cache(new_rate)
        _set_status(int(ing_id), "DONE", None)
        return result
    except Exception as e:
        logger.exception("CBR direct fast-path failed ingest_id=%s url=%s", ing_id, url)
        _set_status(int(ing_id), "ERROR", str(e)[:1000])
        result["ok"] = False
        result["reason"] = "direct_fast_path_failed"
        return result


def replay_url(url: str) -> dict[str, Any]:
    return handle_event(
        _build_event_from_release_url(url, detected_from="replay_url", cache_bust=True),
        allow_previous_release_lookup=True,
    )


def replay_last_n(n: int = 3) -> int:
    logger.info("CBR replay_last_n is disabled in release-only mode; using BOR_REPLAY_URL only")
    event = _build_event_from_release_url(
        DEFAULT_REPLAY_URL,
        detected_from="replay_last_n_disabled_fallback_to_single_url",
        cache_bust=True,
    )
    res = handle_event(event, allow_previous_release_lookup=False)
    logger.info("CBR replay result: %s", json.dumps(res, ensure_ascii=False))
    return 1


def run_live_once() -> dict[str, Any]:
    event = _discover_latest_event()
    if event.get("ok") is False:
        logger.info(
            "CBR not ready path=%s url=%s preview=%s",
            event.get("path"),
            event.get("url"),
            (event.get("preview") or "")[:160],
        )
        return event
    prev_rate, prev_source = _get_prev_rate_from_cache_or_env()
    return handle_event(
        event,
        prev_rate_hint=prev_rate,
        prev_url_hint=None,
        prev_source=prev_source,
        allow_previous_release_lookup=False,
    )


def main() -> None:
    load_dotenv()

    mode = _clean_env_value(os.getenv("BOR_MODE", "replay_url") or "replay_url").lower()
    sleep_s = float(os.getenv("BOR_POLL_SLEEP_SEC", "0.25"))
    replay_n = int(os.getenv("BOR_REPLAY_N", "3"))
    replay_url_value = _clean_env_value(os.getenv("BOR_REPLAY_URL") or DEFAULT_REPLAY_URL) or DEFAULT_REPLAY_URL
    heartbeat_s = float(os.getenv("BOR_HEARTBEAT_SEC", "10"))

    logger.info(
        "CBR ingest starting mode=%s sleep=%s replay_n=%s replay_url=%s",
        mode, sleep_s, replay_n, replay_url_value,
    )

    if mode == "replay_url":
        res = replay_url(replay_url_value)
        logger.info("CBR replay_url result: %s", json.dumps(res, ensure_ascii=False))
        return

    if mode == "replay_last_n":
        replay_last_n(replay_n)
        return

    if mode == "live_once":
        res = run_live_once()
        logger.info("CBR live_once result: %s", json.dumps(res, ensure_ascii=False))
        return

    if mode == "hot":
        last_heartbeat_ts = 0.0
        while True:
            try:
                res = run_live_once()
                now_ts = time.time()
                if not res.get("ok") or res.get("reason") in ("inserted", "updated"):
                    logger.info("CBR live result: %s", json.dumps(res, ensure_ascii=False))
                elif (now_ts - last_heartbeat_ts) >= heartbeat_s:
                    logger.info(
                        "CBR heartbeat ok=%s reason=%s ingest_id=%s direction=%s new_rate=%s prev_rate=%s",
                        res.get("ok"),
                        res.get("reason"),
                        res.get("ingest_id"),
                        res.get("direction"),
                        res.get("new_rate"),
                        res.get("prev_rate"),
                    )
                    last_heartbeat_ts = now_ts
            except Exception:
                logger.exception("CBR ingest hot loop failed")
            time.sleep(sleep_s)
        return

    raise SystemExit(f"Unknown BOR_MODE={mode!r}")


if __name__ == "__main__":
    main()