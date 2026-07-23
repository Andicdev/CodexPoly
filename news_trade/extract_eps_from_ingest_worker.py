# agents/extract_eps_from_ingest_worker.py
from __future__ import annotations

import html as _html
import json
import os
import math
import re
from dataclasses import dataclass
import time
from time import monotonic
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv

from sqlalchemy import select, update, func
from sqlalchemy.sql import text as sql_text

import requests

from common.db import get_session
from common.logger import get_logger

from models.t_ingested_docs import IngestedDoc
from models.t_extracted_values import ExtractedValue
from models.t_company_metric_profile import CompanyMetricProfile
from news_trade.central_bank_policy_history import upsert_policy_decision
from news_trade.trade_from_extracted_values_worker import process_extracted_value


logger = get_logger(__name__)
PrimarySession = get_session("primary")
_LAST_IDLE_LOG = 0.0
SEC_ARCHIVE_BASE = "https://archive.sec-api.io"


DEFAULT_RULESET_V1: dict[str, list[str]] = {
    # GAAP diluted EPS
    "gaap_diluted_eps": [
        r"\bgaap\b[^.]{0,120}\bdiluted\b[^.]{0,120}\b(?:earnings|net income|loss)\b[^.]{0,120}\bper (?:share|sh\.)\b[^$0-9]{0,40}\$?\s*([0-9]+(?:\.[0-9]+)?)",
        r"\bdiluted (?:earnings|net income|loss) per (?:share|sh\.)\b[^$0-9]{0,40}\$?\s*([0-9]+(?:\.[0-9]+)?)",
        r"\bdiluted eps\b[^$0-9]{0,40}\$?\s*([0-9]+(?:\.[0-9]+)?)",
    ],
    # non-GAAP diluted EPS / adjusted diluted EPS
    "non_gaap_diluted_eps": [
        r"\bnon-?gaap\b[^.]{0,160}\bdiluted\b[^.]{0,160}\beps\b[^$0-9]{0,40}\$?\s*([0-9]+(?:\.[0-9]+)?)",
        r"\badjusted\b[^.]{0,160}\bdiluted\b[^.]{0,160}\beps\b[^$0-9]{0,40}\$?\s*([0-9]+(?:\.[0-9]+)?)",
    ],
}


@dataclass(frozen=True)
class ExtractResult:
    metric: str | None
    value: float | None
    confidence: float
    snippet: str | None
    reason: str | None = None


def _compact_text(text: str) -> str:
    return " ".join((text or "").split())

def _normalize_unicode_rate_fractions(text: str) -> str:
    """
    Normalize unicode quarter fractions used in central-bank headlines/text.
    Examples:
      2¼ -> 2.25
      2½ -> 2.5
      2¾ -> 2.75
      ¼  -> 0.25
      ½  -> 0.5
      ¾  -> 0.75
    """
    if not text:
        return text

    s = str(text)

    # number + unicode fraction  => decimal
    s = re.sub(r"(\d+)\s*¼", lambda m: f"{m.group(1)}.25", s)
    s = re.sub(r"(\d+)\s*½", lambda m: f"{m.group(1)}.5", s)
    s = re.sub(r"(\d+)\s*¾", lambda m: f"{m.group(1)}.75", s)

    # standalone fractions
    s = s.replace("¼", "0.25")
    s = s.replace("½", "0.5")
    s = s.replace("¾", "0.75")
    return s

def _coerce_dt_utc(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    try:
        s = str(v).strip()
        if not s:
            return None
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def _normalize_sec_url(url: str) -> str:
    """
    SEC sometimes provides ix?doc=/Archives/...; normalize to https://www.sec.gov/Archives/...
    """
    if not url:
        return url
    u = url.strip()
    try:
        p = urlparse(u)
        if p.path.endswith("/ix"):
            qs = parse_qs(p.query or "")
            doc = qs.get("doc", [None])[0]
            if doc and doc.startswith("/Archives/"):
                return "https://www.sec.gov" + doc
    except Exception:
        pass
    return u

def _to_secapi_download_url(sec_url: str, api_key: str) -> str:
    """
    Convert https://www.sec.gov/Archives/... -> https://archive.sec-api.io/Archives/... ?token=...
    """
    u = _normalize_sec_url(sec_url)
    if u.startswith("https://www.sec.gov"):
        path = u[len("https://www.sec.gov") :]
        return f"{SEC_ARCHIVE_BASE}{path}?token={api_key}"
    if u.startswith("http://www.sec.gov"):
        path = u[len("http://www.sec.gov") :]
        return f"{SEC_ARCHIVE_BASE}{path}?token={api_key}"
    if u.startswith(SEC_ARCHIVE_BASE):
        if "token=" in u:
            return u
        joiner = "&" if "?" in u else "?"
        return f"{u}{joiner}token={api_key}"
    # fallback: treat as path
    joiner = "&" if "?" in u else "?"
    return f"{SEC_ARCHIVE_BASE}{u}{joiner}token={api_key}"

def _html_to_text(s: str) -> str:
    # cheap HTML->text, enough for regex extraction
    s = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", s)
    s = re.sub(r"(?is)<br\\s*/?>", "\n", s)
    s = re.sub(r"(?is)</p\\s*>", "\n", s)
    s = re.sub(r"(?is)</tr\\s*>", "\n", s)
    s = re.sub(r"(?is)</t[dh]\\s*>", " ", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = _html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s+", "\n", s)
    return s.strip()

def _to_int(num_str: str) -> int | None:
    digits = re.sub(r"\D", "", str(num_str))
    return int(digits) if digits else None

def _first_labeled_int(text: str, patterns: list[str]) -> int | None:
    """
    Find first integer for any of the label-based regex patterns.
    Patterns must contain exactly one capturing group for the number.
    """
    if not text:
        return None
    for pat in patterns:
        try:
            m = re.search(pat, text, re.I)
        except re.error:
            continue
        if not m:
            continue
        v = _to_int(m.group(1))
        if v is not None:
            return v
    return None

def normalize_change_bp_to_25bp_bucket(change_bp: float | None) -> float | None:
    """
    Normalize actual policy change into Polymarket-style 25bp brackets.

    Market rule:
    - if change is not one of displayed options, round UP to nearest 25bp bucket.
    - example from market rules: 12.5bp cut => 25bp decrease bracket.

    Output examples:
      -75  -> -75
      -50  -> -50
      -37.5 -> -50
      -25  -> -25
      -12.5 -> -25
       0   -> 0
       12.5 -> 25
       25  -> 25
       40  -> 50
    """
    if change_bp is None:
        return None
    try:
        v = float(change_bp)
    except Exception:
        return None

    if abs(v) < 1e-12:
        return 0.0

    step = 25.0
    sign = -1.0 if v < 0 else 1.0
    bucket_abs = math.ceil(abs(v) / step) * step
    return sign * bucket_abs

def _to_mstr_number(raw: str) -> int | float | None:
    """
    Parse a number token from MSTR BTC Update table.
    Examples: "520" -> 520, "67,068" -> 67068, "34.9" -> 34.9.
    """
    s = str(raw or "").strip().replace(",", "")
    if not s:
        return None
    try:
        if "." in s:
            return float(s)
        return int(s)
    except Exception:
        return None


def parse_mstr_btc_update(text: str) -> dict[str, Any] | None:
    """
    Fail-closed parser for the Strategy/MicroStrategy "BTC Update" table.

    The old parser selected the first grouped number after "BTC Acquired".
    That is unsafe because in a row like:

        520 | $34.9 | $67,068 | 847,363 | $63.8 | $75,651

    the first grouped number is the average purchase price ($67,068), not BTC acquired.

    This parser instead:
      1) finds the BTC Update table headers;
      2) reads values by table position;
      3) validates units and ranges;
      4) cross-checks acquired_btc * average_price ~= aggregate_purchase_price_m.

    If validation fails, tradable fields are returned as None and validation_ok=False.
    That lets the downstream trade gate fail closed instead of trading on a bad parse.
    """
    if not text:
        return None

    compact = _compact_text(text)

    m = re.search(r"\bBTC\s+Update\b", compact, re.I)
    if not m:
        return None

    # Keep the block tight so we do not accidentally consume later unrelated tables.
    block = compact[m.start(): m.start() + 8000]
    end = re.search(
        r"\bUSD\s+Reserve\s+Update\b|\bItem\s+7\.01\b|\bSIGNATURE\b|\bAbout\s+Strategy\b",
        block,
        re.I,
    )
    if end:
        block = block[:end.start()]

    # Drop common footnote artifacts before numeric tokenization.
    block = re.sub(r"\(\s*\d+\s*\)", " ", block)
    block = re.sub(r"[¹²³⁰⁴⁵⁶⁷⁸⁹]", " ", block)

    header_pat = (
        r"\bBTC\s+Acquired\b.*?"
        r"\bAggregate\s+Purchase\s+Price\b.*?"
        r"\bAverage\s+Purchase\s+Price\b.*?"
        r"\bAggregate\s+BTC\s+Holdings\b.*?"
        r"\bAggregate\s+Purchase\s+Price\b.*?"
        r"\bAverage\s+Purchase\s+Price\b"
    )
    hm = re.search(header_pat, block, re.I)
    if not hm:
        return {
            "btc_acquired": None,
            "btc_holdings": None,
            "avg_purchase_price_acquired": None,
            "purchase_price_acquired_m": None,
            "implied_purchase_price_acquired_m": None,
            "validation_ok": False,
            "validation_errors": ["mstr_btc_table_headers_not_found"],
        }

    tail = block[hm.end():]

    # Capture both money and non-money tokens. The $ marker is important because
    # it separates BTC counts from prices/amounts.
    num_pat = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+"
    token_re = re.compile(rf"(?P<money>\$)\s*(?P<mnum>{num_pat})|(?P<num>{num_pat})")

    tokens: list[dict[str, Any]] = []
    for mm in token_re.finditer(tail):
        raw = mm.group("mnum") or mm.group("num")
        money = bool(mm.group("money"))
        value = _to_mstr_number(raw)
        if value is None:
            continue
        tokens.append({"raw": raw, "value": value, "money": money})
        if len(tokens) >= 8:
            break

    errors: list[str] = []
    if len(tokens) < 4:
        return {
            "btc_acquired": None,
            "btc_holdings": None,
            "avg_purchase_price_acquired": None,
            "purchase_price_acquired_m": None,
            "implied_purchase_price_acquired_m": None,
            "validation_ok": False,
            "validation_errors": ["not_enough_table_values"],
            "tokens": tokens,
        }

    btc_token = tokens[0]
    purchase_m_token = tokens[1]
    avg_acq_token = tokens[2]
    holdings_token = tokens[3]

    acquired = None
    if (not btc_token["money"]) and float(btc_token["value"]).is_integer():
        acquired = int(btc_token["value"])

    purchase_m = None
    if purchase_m_token["money"]:
        purchase_m = float(purchase_m_token["value"])

    avg_price = None
    if avg_acq_token["money"] and float(avg_acq_token["value"]).is_integer():
        avg_price = int(avg_acq_token["value"])

    holdings = None
    if (not holdings_token["money"]) and float(holdings_token["value"]).is_integer():
        holdings = int(holdings_token["value"])

    h_min = int(os.getenv("MSTR_HOLDINGS_MIN", "700000"))
    h_max = int(os.getenv("MSTR_HOLDINGS_MAX", "1000000"))
    acquired_max = int(os.getenv("MSTR_ACQUIRED_MAX", "200000"))

    if acquired is None or not (0 <= acquired <= acquired_max):
        errors.append(f"bad_acquired_token={btc_token}")

    # Aggregate purchase price is explicitly in millions in the MSTR BTC Update table.
    if purchase_m is None or not (0 <= purchase_m <= 50000):
        errors.append(f"bad_purchase_price_m_token={purchase_m_token}")

    if avg_price is None or not (10000 <= avg_price <= 300000):
        errors.append(f"bad_avg_purchase_price_token={avg_acq_token}")

    if holdings is None or not (h_min <= holdings <= h_max):
        errors.append(f"bad_holdings_token={holdings_token}")

    implied_purchase_m = None
    if acquired is not None and avg_price is not None:
        implied_purchase_m = acquired * avg_price / 1_000_000.0
        if purchase_m is not None:
            tolerance = max(1.0, purchase_m * 0.05)
            if abs(implied_purchase_m - purchase_m) > tolerance:
                errors.append(
                    "purchase_crosscheck_failed "
                    f"implied_m={implied_purchase_m:.3f} stated_m={purchase_m}"
                )

    validation_ok = not errors

    return {
        "btc_acquired": acquired if validation_ok else None,
        "btc_holdings": holdings if validation_ok else None,
        "avg_purchase_price_acquired": avg_price if validation_ok else None,
        "purchase_price_acquired_m": purchase_m,
        "implied_purchase_price_acquired_m": implied_purchase_m,
        "validation_ok": validation_ok,
        "validation_errors": errors,
        "tokens": tokens[:6],
    }

def parse_bcb_copom_statement(text: str) -> dict[str, Any] | None:
    """
    MVP parser for Banco Central do Brasil / Copom statement.

    Returns:
      {
        "selic_target": float | None,
        "selic_change_bp": float | None,
        "direction": str | None,
        "source_text": str,
      }
    """
    if not text:
        return None

    raw = str(text).strip()
    source_text = raw

    # 1) Try JSON first (details endpoint / list endpoint)
    try:
        data = json.loads(raw)
    except Exception:
        data = None

    if isinstance(data, dict):
        chunks: list[str] = []

        for key in (
            "titulo",
            "title",
            "conteudo",
            "texto",
            "text",
            "content",
            "descricao",
            "corpo",
        ):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                chunks.append(v.strip())

        # details endpoint often returns {"conteudo": [ ... ]}
        for key in ("conteudo", "content", "dados", "data"):
            v = data.get(key)

            if isinstance(v, dict):
                for subk in ("titulo", "texto", "content", "descricao", "textoComunicado"):
                    subv = v.get(subk)
                    if isinstance(subv, str) and subv.strip():
                        chunks.append(subv.strip())

            elif isinstance(v, list):
                for item in v:
                    if not isinstance(item, dict):
                        continue
                    for subk in ("titulo", "texto", "content", "descricao", "textoComunicado"):
                        subv = item.get(subk)
                        if isinstance(subv, str) and subv.strip():
                            chunks.append(subv.strip())

        if chunks:
            source_text = "\n".join(chunks)

    source_text = _compact_text(source_text)

    direction = None
    if re.search(r"\bmaintain(?:s|ed)?\b|\bmaintém\b|\bmanter\b", source_text, re.I):
        direction = "hold"
    elif re.search(r"\braise(?:s|d)?\b|\beleva\b|\baumenta\b", source_text, re.I):
        direction = "hike"
    elif re.search(r"\breduce(?:s|d)?\b|\breduz\b|\bcorta\b|\bcut(?:s)?\b", source_text, re.I):
        direction = "cut"

    patterns = [
        r"(\d{1,2}[.,]\d{2})\s*%\s*(?:a\.a\.|p\.a\.)",
        r"selic[^0-9]{0,40}(\d{1,2}[.,]\d{2})\s*%",
        r"interest rate[^0-9]{0,40}(\d{1,2}[.,]\d{2})\s*%",
    ]

    rate = None
    for pat in patterns:
        m = re.search(pat, source_text, re.I)
        if not m:
            continue
        raw_num = str(m.group(1))
        try:
            rate = float(raw_num.replace(",", "."))
            break
        except Exception:
            continue

    prev_target = None
    try:
        prev_target = float(os.getenv("BCB_PREV_SELIC_TARGET", "15.00"))
    except Exception:
        prev_target = 15.00

    selic_change_bp = None
    if rate is not None and prev_target is not None:
        selic_change_bp = round((rate - prev_target) * 100.0, 6)

    return {
        "selic_target": rate,
        "selic_change_bp": selic_change_bp,
        "direction": direction,
        "source_text": source_text[:4000],
    }

def parse_boc_rate_statement(text: str) -> dict[str, Any] | None:
    """
    Parser for Bank of Canada rate statements / press releases.

    Returns:
      {
        "policy_rate_target": float | None,
        "policy_rate_change_bp": float | None,
        "direction": str | None,
        "source_text": str,
      }
    """
    if not text:
        return None

    raw = str(text).strip()
    source_text = _compact_text(raw)


    # Normalize common unicode fractions used by BoC titles/text like 2¼%, 2½%, 2¾%
    source_text = _normalize_unicode_rate_fractions(source_text)
 
    patterns = [
        r"lowers policy rate to\s*(\d+(?:\.\d+)?)\s*%",
        r"raises policy rate to\s*(\d+(?:\.\d+)?)\s*%",
        r"holds policy rate at\s*(\d+(?:\.\d+)?)\s*%",
        r"target for the overnight rate(?: by \d+(?:\.\d+)? basis points)? to\s*(\d+(?:\.\d+)?)\s*%",
        r"target for the overnight rate at\s*(\d+(?:\.\d+)?)\s*%",
        r"maintains policy rate at\s*(\d+(?:\.\d+)?)\s*%",
        r"held its target for the overnight rate at\s*(\d+(?:\.\d+)?)\s*%",
        r"reduced its target for the overnight rate(?: by \d+(?:\.\d+)? basis points)? to\s*(\d+(?:\.\d+)?)\s*%",
        r"raised its target for the overnight rate(?: by \d+(?:\.\d+)? basis points)? to\s*(\d+(?:\.\d+)?)\s*%",
        r"policy rate(?: by \d+(?:\.\d+)? basis points)? to\s*(\d+(?:\.\d+)?)\s*%",
        r"policy rate at\s*(\d+(?:\.\d+)?)\s*%",
        r"overnight rate[^0-9]{0,40}(\d+(?:\.\d+)?)\s*%",
    ]

    rate = None
    for pat in patterns:
        m = re.search(pat, source_text, re.I)
        if not m:
            continue
        try:
            rate = float(str(m.group(1)))
            break
        except Exception:
            continue


    return {
        "policy_rate_target": rate,
        "policy_rate_change_bp": None,
        "direction": None,
        "source_text": source_text[:4000],
    }
    
def _download_text(
    url: str,
    *,
    ingest_source: str,
    payload: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """
    Variant A: do not store big payloads; fetch by URL at extraction time.
    Returns (plain_text, text_src).
    """
    u = (url or "").strip()
    if not u:
        return "", "empty_url"

    payload = payload or {}
    headers = {"User-Agent": "polymarket-bot/1.0 (extractor)"}
    timeout = int(os.getenv("EXTRACT_FETCH_TIMEOUT", "30"))

    # SEC: use sec-api archive to avoid 403
    if ingest_source == "sec" and ("sec.gov" in u or u.startswith("https://www.sec.gov") or u.startswith("http://www.sec.gov")):
        api_key = (os.getenv("SEC_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("SEC_API_KEY is required to download SEC docs via archive.sec-api.io")
        dl = _to_secapi_download_url(u, api_key)
        r = requests.get(dl, headers=headers, timeout=timeout)
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()
        raw = r.text
        if "html" in ct or "<html" in raw[:500].lower():
            return _html_to_text(raw), "fetch:sec_html"
        return raw.strip(), "fetch:sec_text"

    # BCB/Copom: prefer keeping JSON raw for parser
    if ingest_source == "bcb":
        r = requests.get(u, headers=headers, timeout=timeout)
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()

        if "json" in ct:
            try:
                data = r.json()
                return json.dumps(data, ensure_ascii=False), "fetch:bcb_json"
            except Exception:
                pass

        raw = r.text
        if "html" in ct or "<html" in raw[:500].lower():
            return _html_to_text(raw), "fetch:bcb_html"
        return raw.strip(), "fetch:bcb_text"

    # BOC: prefer payload text from ingest to avoid second network fetch
    if ingest_source == "boc":
        raw_text = str(payload.get("rawText") or "").strip()
        if raw_text:
            return raw_text, "payload:boc_rawText"

        raw_preview = str(payload.get("rawPreview") or "").strip()
        if raw_preview:
            return raw_preview, "payload:boc_rawPreview"

        r = requests.get(u, headers=headers, timeout=timeout)
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()
        raw = r.text
        if "html" in ct or "<html" in raw[:500].lower():
            return _html_to_text(raw), "fetch:boc_html"
        return raw.strip(), "fetch:boc_text"

    # Generic fetch for wire/ir/other
    r = requests.get(u, headers=headers, timeout=timeout)
    r.raise_for_status()
    ct = (r.headers.get("content-type") or "").lower()
    raw = r.text
    if "html" in ct or "<html" in raw[:500].lower():
        return _html_to_text(raw), "fetch:html"
    return raw.strip(), "fetch:text"


def extract_eps(*, text: str, metric: str | None, ruleset: str, overrides: list[dict] | None) -> ExtractResult:
    if not text:
        return ExtractResult(metric=None, value=None, confidence=0.0, snippet=None, reason="empty_text")

    t = _compact_text(text)

    # 1) Overrides first
    if overrides:
        for ov in overrides:
            pat = ov.get("pattern")
            if not pat:
                continue
            mname = (ov.get("metric") or metric or "gaap_diluted_eps").strip()
            grp = int(ov.get("group") or 1)
            flags = re.I if str(ov.get("flags") or "i").lower().find("i") >= 0 else 0

            try:
                m = re.search(pat, t, flags)
            except re.error as e:
                logger.error("Bad override regex metric=%s err=%s pat=%r", mname, str(e), pat)
                continue

            if not m:
                continue
            try:
                raw = m.group(grp)
                raw2 = re.sub(r"[ ,]", "", str(raw))
                val = float(raw2)
                # Handle accounting negatives like (0.02)
                sraw = str(raw)
                if "(" in sraw and ")" in sraw and "-" not in sraw:
                    val = -val
            except Exception:
                continue

            snippet = t[max(0, m.start() - 120): m.end() + 120]
            # preserve raw matched token for debug (appended to snippet)
            snippet2 = f"{snippet} || matched_raw={raw!s}"
            return ExtractResult(metric=mname, value=val, confidence=0.95, snippet=snippet2, reason="override_match")

    # 2) Ruleset
    rs = DEFAULT_RULESET_V1 if (ruleset or "default_eps_v1") == "default_eps_v1" else DEFAULT_RULESET_V1
    metrics_to_try = [metric] if metric else list(rs.keys())

    for mname in metrics_to_try:
        if not mname:
            continue
        for pat in rs.get(mname, []):
            try:
                m = re.search(pat, t, re.I)
            except re.error as e:
                logger.error("Bad ruleset regex metric=%s err=%s pat=%r", mname, str(e), pat)
                continue
            if not m:
                continue
            try:
                raw = m.group(1)
                raw2 = re.sub(r"[ ,]", "", str(raw))
                val = float(raw2)
                # Handle accounting negatives like (0.02)
                sraw = str(raw)
                if "(" in sraw and ")" in sraw and "-" not in sraw:
                    val = -val
            except Exception:
                continue

            snippet = t[max(0, m.start() - 120): m.end() + 120]
            snippet2 = f"{snippet} || matched_raw={raw!s}"
            return ExtractResult(metric=mname, value=val, confidence=0.7, snippet=snippet2, reason="ruleset_match")

    return ExtractResult(metric=None, value=None, confidence=0.0, snippet=None, reason="no_match")


def _claim_batch(*, limit: int) -> list[dict[str, Any]]:
    """
    Atomically claim NEW rows -> PROCESSING using SKIP LOCKED.
    Returns lightweight dicts (id, ticker, company_id, payload, url, doc_type, source).
    """
    with PrimarySession() as s:
        q = sql_text(
            """
            WITH cte AS (
              SELECT id
              FROM ingested_docs
              WHERE status = 'NEW'
              ORDER BY created_at ASC
              FOR UPDATE SKIP LOCKED
              LIMIT :limit
            )
            UPDATE ingested_docs d
            SET status = 'PROCESSING', updated_at = now()
            FROM cte
            WHERE d.id = cte.id
            RETURNING d.id, d.company_id, d.ticker, d.cik, d.source, d.doc_type, d.url, d.payload, d.published_at;
            """
        )
        rows = s.execute(q, {"limit": int(limit)}).mappings().all()
        s.commit()
        return [dict(r) for r in rows]

def load_ingested_doc_for_fast_path(ingest_id: int) -> dict[str, Any] | None:
    with PrimarySession() as s:
        row = s.execute(
            select(
                IngestedDoc.id,
                IngestedDoc.company_id,
                IngestedDoc.ticker,
                IngestedDoc.cik,
                IngestedDoc.source,
                IngestedDoc.doc_type,
                IngestedDoc.url,
                IngestedDoc.payload,
                IngestedDoc.published_at,
            ).where(IngestedDoc.id == int(ingest_id))
        ).first()

    if not row:
        return None

    return {
        "id": int(row[0]),
        "company_id": int(row[1]),
        "ticker": row[2],
        "cik": row[3],
        "source": row[4],
        "doc_type": row[5],
        "url": row[6],
        "payload": row[7],
        "published_at": row[8],
    }

def claim_ingested_doc_for_fast_path(ingest_id: int) -> bool:
    with PrimarySession() as s:
        res = s.execute(
            update(IngestedDoc)
            .where(
                IngestedDoc.id == int(ingest_id),
                IngestedDoc.status == "NEW",
            )
            .values(status="PROCESSING", updated_at=func.now())
        )
        s.commit()
        return int(res.rowcount or 0) == 1

def _set_status(ingest_id: int, status: str, error: str | None = None) -> None:
    with PrimarySession() as s:
        s.execute(
            update(IngestedDoc)
            .where(IngestedDoc.id == int(ingest_id))
            .values(status=status, error=error, updated_at=func.now())
        )
        s.commit()

def _load_profiles_for_company(company_id: int) -> list[dict[str, Any]]:
    """
    Новый источник правил: company_metric_profile.
    Возвращаем список профилей (id, metric_key, source_priority, doc_types, matchers).
    """
    with PrimarySession() as s:
        rows = (
            s.execute(
                select(
                    CompanyMetricProfile.id,
                    CompanyMetricProfile.metric_key,
                    CompanyMetricProfile.source_priority,
                    CompanyMetricProfile.doc_types,
                    CompanyMetricProfile.matchers,
                )
                .where(
                    CompanyMetricProfile.enabled.is_(True),
                    CompanyMetricProfile.company_id == int(company_id),
                )
                .order_by(CompanyMetricProfile.id.asc())
            )
            .all()
        )
    out: list[dict[str, Any]] = []
    for pid, metric_key, source_priority, doc_types, matchers in rows:
        out.append(
            {
                "profile_id": int(pid),
                "metric_key": str(metric_key),
                "source_priority": list(source_priority or []),
                "doc_types": list(doc_types or []),
                "matchers": dict(matchers or {}),
            }
        )
    return out

def _profile_applies(profile: dict[str, Any], *, ingest_source: str, ingest_doc_type: str) -> bool:
    sp = [str(x).lower() for x in (profile.get("source_priority") or []) if x]
    dt = [str(x).upper() for x in (profile.get("doc_types") or []) if x]
    if sp and str(ingest_source).lower() not in sp:
        return False
    if dt and str(ingest_doc_type).upper() not in dt:
        return False
    return True

def _passes_excludes(text: str, exclude_regexes: list[str] | None) -> bool:
    if not exclude_regexes:
        return True
    t = _compact_text(text)
    for pat in exclude_regexes:
        try:
            if re.search(pat, t):
                return False
        except re.error:
            logger.warning("Bad exclude regex: %r", pat)
            continue
    return True


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

def process_ingested_doc(r: dict[str, Any]) -> bool:
    ing_id = int(r["id"])
    ticker = str(r["ticker"] or "").strip().upper()
    company_id = int(r["company_id"])
    ingest_source = str(r.get("source") or "").lower()
    ingest_doc_type = str(r.get("doc_type") or "").upper()

    url = str(r.get("url") or "").strip()
    payload_obj = r.get("payload") or {}
    t_fetch0 = time.perf_counter()
    text, text_src = _download_text(
        url,
        ingest_source=ingest_source,
        payload=payload_obj,
    )
    fetch_ms = int((time.perf_counter() - t_fetch0) * 1000)

    logger.info(
        "ingest_id=%s ticker=%s fetched text_src=%s text_len=%s fetch_ms=%s url=%s",
        ing_id, ticker, text_src, len(text or ""), fetch_ms, url
    )

    profiles = _load_profiles_for_company(company_id)
    if not profiles:
        _set_status(ing_id, "SKIPPED", error="no_company_metric_profiles")
        return False

    mstr_btc = None
    if any(((p.get("matchers") or {}).get("kind") == "mstr_btc_update") for p in profiles):
        mstr_btc = parse_mstr_btc_update(text)
        logger.info(
            "MSTR_BTC_PARSE ingest_id=%s ticker=%s ok=%s parsed=%s",
            ing_id, ticker, bool(mstr_btc), mstr_btc
        )
    
    bcb_copom = None
    if any(((p.get("matchers") or {}).get("kind") == "bcb_copom_statement") for p in profiles):
        bcb_copom = parse_bcb_copom_statement(text)
        logger.info(
            "BCB_COPOM_PARSE ingest_id=%s ticker=%s ok=%s parsed=%s",
            ing_id, ticker, bool(bcb_copom), bcb_copom
        )

    boc_rate = None
    boc_parse_ready = False
    if any(((p.get("matchers") or {}).get("kind") == "boc_rate_statement") for p in profiles):
        boc_rate = parse_boc_rate_statement(text)
        logger.info(
            "BOC_RATE_PARSE ingest_id=%s ticker=%s ok=%s parsed=%s",
            ing_id, ticker, bool(boc_rate), boc_rate
        )

    boc_decision_time_utc = None
    boc_policy_row = None
    if boc_rate:
        payload_obj = r.get("payload") or {}
        boc_decision_time_utc = (
            _coerce_dt_utc(payload_obj.get("publishedAt"))
            or _coerce_dt_utc(payload_obj.get("decisionDate"))
            or _coerce_dt_utc(r.get("published_at"))
        )

        current_target = boc_rate.get("policy_rate_target")
        boc_parse_ready = current_target is not None

        if not boc_parse_ready:
            logger.warning(
                "BOC_PARSE_INCOMPLETE ingest_id=%s ticker=%s decision_time=%s parsed=%s",
                ing_id,
                ticker,
                boc_decision_time_utc.isoformat() if boc_decision_time_utc else None,
                boc_rate,
            )

        if boc_decision_time_utc and boc_parse_ready:

            boc_policy_row = upsert_policy_decision(
                bank_code="BOC",
                instrument_code="OVERNIGHT_RATE",
                decision_time_utc=boc_decision_time_utc,
                target_value=float(current_target) if current_target is not None else None,
                direction=None,
                source=r.get("source"),
                source_doc_type=r.get("doc_type"),
                source_url=r.get("url"),
                ingest_id=ing_id,
                evidence={
                    "kind": "boc_rate_statement",
                    "parsed": boc_rate,
                    "text_src": text_src,
                    "stage": "precompute_once_per_ingest",
                },
            )
            logger.info(
                "BOC_POLICY_PRECOMPUTE ingest_id=%s ticker=%s decision_time=%s target=%s change_bps=%s",
                ing_id,
                ticker,
                boc_decision_time_utc.isoformat() if boc_decision_time_utc else None,
                current_target,
                boc_policy_row.get("change_bps") if boc_policy_row else None,
            )

    wrote_any = False
    for p in profiles:
        if not _profile_applies(p, ingest_source=ingest_source, ingest_doc_type=ingest_doc_type):
            continue

        matchers = p.get("matchers") or {}
        extract_cfg = matchers.get("extract") if isinstance(matchers.get("extract"), dict) else matchers

        if str(matchers.get("kind") or "").lower() == "bcb_copom_statement":
            field = str(matchers.get("field") or "").strip()
            parsed = bcb_copom or {}
            val = parsed.get(field) if parsed else None
            reason = "bcb_copom_statement" if val is not None else "bcb_copom_no_match"
            conf = 0.95 if val is not None else 0.0

            # Generic CB policy history layer:
            # for change metric, compute delta from previous stored target instead of env/params.
            if field == "selic_change_bp":
                current_target = parsed.get("selic_target") if parsed else None
                current_direction = parsed.get("direction") if parsed else None

                decision_time_utc = (
                    _coerce_dt_utc(r.get("published_at"))
                    or _coerce_dt_utc((r.get("payload") or {}).get("publishedAt"))
                    or _coerce_dt_utc((r.get("payload") or {}).get("dataReferencia"))
                    or datetime.now(timezone.utc)
                )

                if current_target is not None or current_direction is not None:
                    policy_row = upsert_policy_decision(
                        bank_code="BCB",
                        instrument_code="SELIC",
                        decision_time_utc=decision_time_utc,
                        target_value=float(current_target) if current_target is not None else None,
                        direction=str(current_direction) if current_direction is not None else None,
                        source=r.get("source"),
                        source_doc_type=r.get("doc_type"),
                        source_url=r.get("url"),
                        ingest_id=ing_id,
                        evidence={
                            "kind": "bcb_copom_statement",
                            "parsed": parsed,
                            "profile_id": p["profile_id"],
                            "text_src": text_src,
                        },
                    )
                    val = policy_row.get("change_bps")
                    reason = "bcb_copom_change_from_policy_history" if val is not None else "bcb_copom_change_unknown"
                    conf = 0.95 if val is not None else 0.0

            logger.info(
                "EXTRACT ingest_id=%s ticker=%s profile_id=%s metric_key=%s kind=bcb_copom_statement field=%s value=%s",
                ing_id, ticker, p["profile_id"], p["metric_key"], field, val
            )

            evidence = {
                "text_src": text_src,
                "reason": reason,
                "url": r.get("url"),
                "source": r.get("source"),
                "doc_type": r.get("doc_type"),
                "profile_id": p["profile_id"],
                "kind": "bcb_copom_statement",
                "field": field,
                "parsed": parsed,
            }

            ev_id = _insert_extracted_value(
                company_id=company_id,
                ingest_id=ing_id,
                ticker=ticker,
                metric_key=str(p["metric_key"]),
                value_num=float(val) if val is not None else None,
                value_raw=str(val) if val is not None else None,
                confidence=float(conf),
                evidence=evidence,
                resolver_name="profile_custom",
                resolver_ver="bcb_copom_statement_v2",
            )

            try:
                process_extracted_value(
                    {
                        "id": ev_id,
                        "company_id": company_id,
                        "ingest_id": ing_id,
                        "ticker": ticker,
                        "metric_key": str(p["metric_key"]),
                        "value_num": float(val) if val is not None else None,
                        "value_raw": str(val) if val is not None else None,
                        "confidence": float(conf),
                        "evidence": evidence,
                    },
                    execution_path="fast",
                    update_trade_status=False,
                )
            except Exception:
                logger.exception(
                    "fast-path process failed ingest_id=%s ev_id=%s ticker=%s metric_key=%s",
                    ing_id, ev_id, ticker, p["metric_key"]
                )

            wrote_any = True
            continue

        if str(matchers.get("kind") or "").lower() == "boc_rate_statement":
            field = str(matchers.get("field") or "").strip()
            parsed = boc_rate or {}
            val = parsed.get(field) if parsed else None
            reason = "boc_rate_statement" if val is not None else "boc_rate_no_match"
            conf = 0.95 if val is not None else 0.0

            if not boc_parse_ready:
                val = None
                reason = "boc_parse_incomplete"
                conf = 0.0

            if boc_parse_ready and field in ("policy_rate_change_bp", "policy_rate_change_bucket_bp"):
 
                actual_change_bp = boc_policy_row.get("change_bps") if boc_policy_row else None

                if field == "policy_rate_change_bp":
                    val = actual_change_bp
                    reason = "boc_change_from_policy_history" if val is not None else "boc_change_unknown"
                    conf = 0.95 if val is not None else 0.0
                elif field == "policy_rate_change_bucket_bp":
                    val = normalize_change_bp_to_25bp_bucket(actual_change_bp)
                    reason = "boc_change_bucket_from_policy_history" if val is not None else "boc_change_bucket_unknown"
                    conf = 0.95 if val is not None else 0.0

            logger.info(
                "EXTRACT ingest_id=%s ticker=%s profile_id=%s metric_key=%s kind=boc_rate_statement field=%s value=%s",
                ing_id, ticker, p["profile_id"], p["metric_key"], field, val
            )

            evidence = {
                "text_src": text_src,
                "reason": reason,
                "url": r.get("url"),
                "source": r.get("source"),
                "doc_type": r.get("doc_type"),
                "profile_id": p["profile_id"],
                "kind": "boc_rate_statement",
                "field": field,
                "parsed": parsed,
                "decision_time_utc": boc_decision_time_utc.isoformat() if boc_decision_time_utc else None,
            }

            ev_id = _insert_extracted_value(
                company_id=company_id,
                ingest_id=ing_id,
                ticker=ticker,
                metric_key=str(p["metric_key"]),
                value_num=float(val) if val is not None else None,
                value_raw=str(val) if val is not None else None,
                confidence=float(conf),
                evidence=evidence,
                resolver_name="profile_custom",
                resolver_ver="boc_rate_statement_v1",
            )

            try:
                process_extracted_value(
                    {
                        "id": ev_id,
                        "company_id": company_id,
                        "ingest_id": ing_id,
                        "ticker": ticker,
                        "metric_key": str(p["metric_key"]),
                        "value_num": float(val) if val is not None else None,
                        "value_raw": str(val) if val is not None else None,
                        "confidence": float(conf),
                        "evidence": evidence,
                    },
                    execution_path="fast",
                    update_trade_status=False,
                )
            except Exception:
                logger.exception(
                    "fast-path process failed ingest_id=%s ev_id=%s ticker=%s metric_key=%s",
                    ing_id, ev_id, ticker, p["metric_key"]
                )

            wrote_any = True
            continue

        if str(matchers.get("kind") or "").lower() == "mstr_btc_update":
            field = str(matchers.get("field") or "").strip()
            val = (mstr_btc or {}).get(field) if mstr_btc else None
            reason = "mstr_btc_update" if val is not None else "mstr_btc_update_no_match"
            conf = 0.95 if val is not None else 0.0

            logger.info(
                "EXTRACT ingest_id=%s ticker=%s profile_id=%s metric_key=%s kind=mstr_btc_update field=%s value=%s",
                ing_id, ticker, p["profile_id"], p["metric_key"], field, val
            )

            evidence = {
                "text_src": text_src,
                "reason": reason,
                "url": r.get("url"),
                "source": r.get("source"),
                "doc_type": r.get("doc_type"),
                "profile_id": p["profile_id"],
                "kind": "mstr_btc_update",
                "field": field,
                "parsed": mstr_btc,
            }

            ev_id = _insert_extracted_value(
                company_id=company_id,
                ingest_id=ing_id,
                ticker=ticker,
                metric_key=str(p["metric_key"]),
                value_num=float(val) if val is not None else None,
                value_raw=str(val) if val is not None else None,
                confidence=float(conf),
                evidence=evidence,
                resolver_name="profile_custom",
                resolver_ver="mstr_btc_update_v1",
            )

            try:
                process_extracted_value(
                    {
                        "id": ev_id,
                        "company_id": company_id,
                        "ingest_id": ing_id,
                        "ticker": ticker,
                        "metric_key": str(p["metric_key"]),
                        "value_num": float(val) if val is not None else None,
                        "value_raw": str(val) if val is not None else None,
                        "confidence": float(conf),
                        "evidence": evidence,
                    },
                    execution_path="fast",
                    update_trade_status=False,
                )
            except Exception:
                logger.exception(
                    "fast-path process failed ingest_id=%s ev_id=%s ticker=%s metric_key=%s",
                    ing_id, ev_id, ticker, p["metric_key"]
                )

            wrote_any = True
            continue

        ruleset = str(extract_cfg.get("ruleset") or "default_eps_v1").strip()
        metric = extract_cfg.get("metric")
        overrides = extract_cfg.get("overrides") or []
        exclude_regexes = extract_cfg.get("exclude_regexes") or []

        if text and not _passes_excludes(text, exclude_regexes):
            evidence = {
                "text_src": text_src,
                "reason": "excluded_by_profile",
                "exclude_regexes": exclude_regexes,
                "url": r.get("url"),
                "source": r.get("source"),
                "doc_type": r.get("doc_type"),
                "profile_id": p["profile_id"],
            }
            ev_id = _insert_extracted_value(
                company_id=company_id,
                ingest_id=ing_id,
                ticker=ticker,
                metric_key=str(p["metric_key"]),
                value_num=None,
                value_raw=None,
                confidence=0.0,
                evidence=evidence,
                resolver_name="profile_regex",
                resolver_ver="v1",
            )

            try:
                process_extracted_value(
                    {
                        "id": ev_id,
                        "company_id": company_id,
                        "ingest_id": ing_id,
                        "ticker": ticker,
                        "metric_key": str(p["metric_key"]),
                        "value_num": None,
                        "value_raw": None,
                        "confidence": 0.0,
                        "evidence": evidence,
                    },
                    execution_path="fast",
                    update_trade_status=False,
                )
            except Exception:
                logger.exception(
                    "fast-path process failed ingest_id=%s ev_id=%s ticker=%s metric_key=%s",
                    ing_id, ev_id, ticker, p["metric_key"]
                )

            wrote_any = True
            continue

        res = extract_eps(text=text, metric=metric, ruleset=ruleset, overrides=overrides)

        logger.info(
            "EXTRACT ingest_id=%s ticker=%s profile_id=%s metric_key=%s reason=%s value=%s conf=%.2f url=%s",
            ing_id, ticker, p["profile_id"], p["metric_key"], res.reason, res.value, res.confidence, url
        )

        evidence = {
            "text_src": text_src,
            "reason": res.reason,
            "snippet": res.snippet,
            "url": r.get("url"),
            "source": r.get("source"),
            "doc_type": r.get("doc_type"),
            "profile_id": p["profile_id"],
            "ruleset": ruleset,
            "metric": metric,
        }

        ev_id = _insert_extracted_value(
            company_id=company_id,
            ingest_id=ing_id,
            ticker=ticker,
            metric_key=str(p["metric_key"]),
            value_num=res.value,
            value_raw=(str(res.value) if res.value is not None else None),
            confidence=float(res.confidence),
            evidence=evidence,
            resolver_name="profile_regex",
            resolver_ver="v1",
        )

        try:
            process_extracted_value(
                {
                    "id": ev_id,
                    "company_id": company_id,
                    "ingest_id": ing_id,
                    "ticker": ticker,
                    "metric_key": str(p["metric_key"]),
                    "value_num": res.value,
                    "value_raw": (str(res.value) if res.value is not None else None),
                    "confidence": float(res.confidence),
                    "evidence": evidence,
                },
                execution_path="fast",
                update_trade_status=False,
            )
        except Exception:
            logger.exception(
                "fast-path process failed ingest_id=%s ev_id=%s ticker=%s metric_key=%s",
                ing_id, ev_id, ticker, p["metric_key"]
            )

        wrote_any = True

    if not wrote_any:
        _set_status(ing_id, "SKIPPED", error="no_applicable_profiles_for_source_or_doc_type")
        return False

    _set_status(ing_id, "DONE", error=None)
    return True

def run_once(*, batch: int = 25) -> int:
    claimed = _claim_batch(limit=batch)
    if not claimed:
        return 0

    for r in claimed:
        ing_id = int(r["id"])
        ticker = str(r["ticker"] or "").strip().upper()
        try:
            process_ingested_doc(r)
        except Exception as e:
            logger.exception("extract failed ingest_id=%s ticker=%s", ing_id, ticker)
            _set_status(ing_id, "ERROR", error=str(e)[:800])

    return len(claimed)


def main() -> None:
    load_dotenv()
    batch = int(os.getenv("EXTRACT_BATCH", "25"))
    sleep_s = float(os.getenv("EXTRACT_SLEEP_SEC", "1.0"))
    idle_log_sec = float(os.getenv("IDLE_LOG_SEC", "60"))  # 0 = disable idle heartbeat logs

    logger.info("extract_worker starting batch=%s sleep=%s", batch, sleep_s)

    while True:
        t0 = time.perf_counter()
        n = run_once(batch=batch)
        if n == 0:
            dt = time.perf_counter() - t0
            if idle_log_sec > 0:
                global _LAST_IDLE_LOG
                now = monotonic()
                if now - _LAST_IDLE_LOG >= idle_log_sec:
                    _LAST_IDLE_LOG = now
                    logger.info("idle: no rows (dt=%.3fs)", dt)
            time.sleep(sleep_s)


if __name__ == "__main__":
    main()