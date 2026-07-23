# common/rpc_fills.py
"""RPC-based fallback for Polymarket OrderFilled events (Polygon).

This module provides a polling-based iterator over OrderFilled logs via a standard
EVM JSON-RPC endpoint (e.g. Infura Polygon HTTPS endpoint).

Design goals:
- Minimal dependencies (requests only)
- Deterministic ordering + de-dup friendly IDs (txHash:logIndex)
- Timestamp-based cursor compatibility: can start from existing from_ts watermark
  by estimating the starting block via block timestamps.

Notes:
- For production-grade reliability you typically combine:
  * WebSocket 'logs' subscription for realtime
  * Periodic backfill via eth_getLogs for gaps
  This module implements the backfill/polling part first.
"""

from __future__ import annotations

import os
import time
import gc
import logging
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

RPC_MEM_DEBUG = os.getenv("RPC_MEM_DEBUG", "1") == "1"

def _rss_mb() -> float:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    return round(int(parts[1]) / 1024.0, 1)
    except Exception:
        pass
    return -1.0

def _memlog(stage: str, **kwargs: Any) -> None:
    if not RPC_MEM_DEBUG:
        return
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
    log.info("[rpc-fills][mem] stage=%s rss_mb=%.1f %s", stage, _rss_mb(), extra)

# ── Retry/backoff tuning (env overrides optional) ───────────────────────────
# Public RPC endpoints may return HTTP 429 during bursts (binary search by ts, backfill).
RPC_HTTP_MAX_RETRIES = int(os.getenv("RPC_HTTP_MAX_RETRIES", "5"))
RPC_HTTP_BACKOFF_BASE_S = float(os.getenv("RPC_HTTP_BACKOFF_BASE_S", "1.5"))
RPC_HTTP_BACKOFF_CAP_S = float(os.getenv("RPC_HTTP_BACKOFF_CAP_S", "30"))

# ── Optional: Infura credits estimation (best-effort) ─────────────────────
# Infura bills "credits" per RPC request based on the method. The dashboard is
# the source of truth; this block estimates spend from the RPC methods we call.
#
# Enable/disable via env:
#   INFURA_CREDITS_ENABLED=1|0
#   INFURA_CREDITS_LOG_EVERY_S=60
#   INFURA_RPC_CREDIT_COSTS="eth_getLogs=255,eth_getBlockByNumber=80"
INFURA_CREDITS_ENABLED = os.getenv("INFURA_CREDITS_ENABLED", "1") not in {"0", "false", "False"}
INFURA_CREDITS_LOG_EVERY_S = float(os.getenv("INFURA_CREDITS_LOG_EVERY_S", "60"))

# Default costs taken from the Infura/MetaMask RPC credit cost table ("Base" RPC methods).
# Keep this small and focused on methods used by this module.
_DEFAULT_RPC_CREDIT_COSTS: dict[str, int] = {
    "eth_getLogs": 255,
    "eth_getBlockByNumber": 80,
    "eth_blockNumber": 80,
    # used for ERC20 balanceOf calls (wallet enrichment)
    "eth_call": 80,
}

def _parse_rpc_credit_cost_overrides(raw: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k or not v:
            continue
        try:
            out[k] = int(v)
        except Exception:
            continue
    return out

_RPC_CREDIT_COSTS: dict[str, int] = {
    **_DEFAULT_RPC_CREDIT_COSTS,
    **_parse_rpc_credit_cost_overrides(os.getenv("INFURA_RPC_CREDIT_COSTS", "")),
}

def _rpc_credit_cost(method: str) -> int:
    return int(_RPC_CREDIT_COSTS.get(method, 0))


class RpcHttpStatusError(RuntimeError):
    """Raised when RPC endpoint responds with non-2xx HTTP status after retries."""
    def __init__(self, *, status_code: int, url: str, message: str = "") -> None:
        super().__init__(message or f"HTTP {status_code} for url: {url}")
        self.status_code = int(status_code)
        self.url = url

class RpcTooManyResultsError(RuntimeError):
    """Raised when eth_getLogs returns provider 'too many results' (-32005 / >10000 logs).

    This is not transient; retrying the same request won't help. The caller should split
    the block range (see _get_logs_adaptive).
    """
    pass

def _is_jsonrpc_too_many_results(err: Any) -> bool:
    """Best-effort detection of provider limit for eth_getLogs (>10k results)."""
    try:
        if isinstance(err, dict):
            code = err.get("code")
            msg = str(err.get("message") or "")
            if code == -32005:
                return True
            if "more than 10000 results" in msg.lower():
                return True
            if "query returned more than 10000 results" in msg.lower():
                return True
        # fallback to string
        s = str(err) or ""
        s_l = s.lower()
        return ("more than 10000 results" in s_l) or ("code" in s_l and "-32005" in s_l)
    except Exception:
        return False

def _sleep_jitter(seconds: float) -> None:
    # jitter to avoid thundering herd on retries
    try:
        j = 0.85 + (random.random() * 0.30)
        time.sleep(max(0.0, float(seconds)) * j)
    except Exception:
        time.sleep(max(0.0, float(seconds)))

# ── Defaults (keep .env minimal; override only secrets/URLs) ───────────────────
# We intentionally keep these as module defaults so you don't need to bloat .env.
DEFAULT_RPC_TIMEOUT_S = 25.0
DEFAULT_CONFIRMATIONS = 15
DEFAULT_CHUNK_BLOCKS = 50        # Safe baseline for Infura/Polygon getLogs
MIN_CHUNK_BLOCKS = 5             # Don't split below this unless unavoidable
DEFAULT_AVG_BLOCK_TIME_S = 2.1   # Polygon ~2s; used only for timestamp->block estimate
MAX_SPLIT_DEPTH = 20             # safety for recursion on splits

# CLOB V2 OrderFilled:
#   OrderFilled(
#       index_topic_1 bytes32 orderHash,
#       index_topic_2 address maker,
#       index_topic_3 address taker,
#       uint8 side,
#       uint256 tokenId,
#       uint256 makerAmountFilled,
#       uint256 takerAmountFilled,
#       uint256 fee,
#       bytes32 builder,
#       bytes32 metadata
#   )
#
# Topic0 = keccak256(
#   "OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)"
# )
ORDER_FILLED_TOPIC0 = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"

DEFAULT_EXCHANGE_ADDRESSES = [
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",  # CTFExchange
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",  # NegRisk CTFExchange
]

def _to_hex_block(n: int) -> str:
    return hex(int(n))

def _hex_to_int(x: str) -> int:
    return int(x, 16)

def _topic_to_address(topic: str) -> str:
    # topic is 0x + 64 hex chars; address is last 40 hex
    h = topic[2:]
    return "0x" + h[-40:]

def _topic_to_bytes32(topic: str) -> str:
    # keep as 0x...
    return topic

def _data_words(data_hex: str) -> List[str]:
    h = data_hex[2:] if data_hex.startswith("0x") else data_hex
    # split into 32-byte words (64 hex chars)
    return ["0x" + h[i:i+64] for i in range(0, len(h), 64) if h[i:i+64]]

def _word_to_int(word: str) -> int:
    return int(word, 16)

def _is_too_many_results_error(exc: Exception) -> bool:
    """
    Infura/Polygon typical error for eth_getLogs:
      code: -32005, message: 'query returned more than 10000 results...'
    """
    s = str(exc) or ""
    if "more than 10000 results" in s.lower():
        return True
    if "code': -32005" in s or '"code": -32005' in s:
        return True
    return False

def _extract_suggested_range(exc: Exception) -> Optional[Tuple[int, int]]:
    """
    Sometimes provider suggests a better block range like:
      'Try with this block range [0xAAA, 0xBBB]'
    We'll parse it if present (best effort).
    """
    s = str(exc) or ""
    m = re.search(r"\[\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*\]", s)
    if not m:
        return None
    try:
        return int(m.group(1), 16), int(m.group(2), 16)
    except Exception:
        return None

def _get_logs_adaptive(
    rpc: "RpcClient",
    *,
    from_block: int,
    to_block: int,
    addresses: List[str],
    topic0: str,
    depth: int = 0,
    progress: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    eth_getLogs with adaptive splitting if provider returns "too many results".
    """
    if from_block > to_block:
        return []
    params = {
        "fromBlock": _to_hex_block(from_block),
        "toBlock": _to_hex_block(to_block),
        "address": addresses,
        "topics": [topic0],
    }
    try:
        return rpc.get_logs(params)
    except Exception as e:
        if not _is_too_many_results_error(e):
            raise

        if progress is not None:
            progress["too_many_results_hits"] = int(progress.get("too_many_results_hits") or 0) + 1
            progress["too_many_results_last_range"] = (int(from_block), int(to_block))


        if depth >= MAX_SPLIT_DEPTH:
            raise RuntimeError(f"getLogs split depth exceeded for range {from_block}-{to_block}") from e

        # Provider might suggest a safe range — respect it if it narrows.
        suggested = _extract_suggested_range(e)
        if suggested:
            s_from, s_to = suggested
            if s_from >= from_block and s_to <= to_block and (s_to - s_from) < (to_block - from_block):
                log.warning(
                    "[rpc-fills] getLogs too many results; use suggested range %s..%s (was %s..%s)",
                    s_from, s_to, from_block, to_block
                )
                return _get_logs_adaptive(
                    rpc,
                    from_block=s_from,
                    to_block=s_to,
                    addresses=addresses,
                    topic0=topic0,
                    depth=depth + 1,
                    progress=progress,
                )

        # If range already tiny, we can't split further.
        if (to_block - from_block) <= MIN_CHUNK_BLOCKS:
            raise

        mid = (from_block + to_block) // 2
        log.warning(
            "[rpc-fills] getLogs too many results; split range %s..%s -> %s..%s + %s..%s",
            from_block, to_block, from_block, mid, mid + 1, to_block
        )
        left = _get_logs_adaptive(
            rpc,
            from_block=from_block,
            to_block=mid,
            addresses=addresses,
            topic0=topic0,
            depth=depth + 1,
            progress=progress,
        )
        right = _get_logs_adaptive(
            rpc,
            from_block=mid + 1,
            to_block=to_block,
            addresses=addresses,
            topic0=topic0,
            depth=depth + 1,
            progress=progress,
        )
        return (left or []) + (right or [])

@dataclass
class RpcClient:
    url: str
    timeout: float = DEFAULT_RPC_TIMEOUT_S
    session: Optional[requests.Session] = None

    # ── credits telemetry (best-effort; dashboard remains source of truth) ──
    _rpc_started_ts: float = field(default_factory=time.time, init=False, repr=False)
    _rpc_last_log_ts: float = field(default=0.0, init=False, repr=False)
    _rpc_requests_sent: int = field(default=0, init=False, repr=False)
    _rpc_billed_credits_est: int = field(default=0, init=False, repr=False)
    _rpc_attempts_by_method: dict[str, int] = field(default_factory=lambda: defaultdict(int), init=False, repr=False)
    _rpc_billed_by_method: dict[str, int] = field(default_factory=lambda: defaultdict(int), init=False, repr=False)
    _rpc_unknown_methods: set[str] = field(default_factory=set, init=False, repr=False)


    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def _note_rpc_attempt(self, method: str) -> None:
        if not INFURA_CREDITS_ENABLED:
            return
        self._rpc_requests_sent += 1
        self._rpc_attempts_by_method[method] += 1

    def _note_rpc_billed_estimate(self, method: str, *, status_code: int) -> None:
        """Update best-effort billed credits estimate.

        Based on Infura guidance:
        - HTTP 429 and 402 do not count.
        - HTTP 5xx do not count.
        - Other 4xx count as 1 credit.
        - Successful HTTP 200 counts by method cost.
        """
        if not INFURA_CREDITS_ENABLED:
            return

        sc = int(status_code)
        if sc == 429 or sc == 402 or sc >= 500:
            return

        if 400 <= sc < 500:
            cost = 1
        else:
            cost = _rpc_credit_cost(method)
            if cost == 0 and method not in self._rpc_unknown_methods:
                self._rpc_unknown_methods.add(method)
                log.warning(
                    "infura credits: unknown method cost for %s (treating as 0; set INFURA_RPC_CREDIT_COSTS to override)",
                    method,
                )

        self._rpc_billed_credits_est += int(cost)
        self._rpc_billed_by_method[method] += int(cost)

    def _maybe_log_rpc_credits(self) -> None:
        if not INFURA_CREDITS_ENABLED:
            return
        now = time.time()
        if self._rpc_last_log_ts and (now - self._rpc_last_log_ts) < INFURA_CREDITS_LOG_EVERY_S:
            return
        self._rpc_last_log_ts = now

        elapsed_s = max(1e-6, now - self._rpc_started_ts)
        credits = float(self._rpc_billed_credits_est)
        cph = credits / elapsed_s * 3600.0
        cps = credits / elapsed_s

        # Top methods by estimated billed credits
        top = sorted(self._rpc_billed_by_method.items(), key=lambda kv: kv[1], reverse=True)[:6]
        top_s = ", ".join(
            f"{m}:{c}c/{self._rpc_attempts_by_method.get(m, 0)}r" for (m, c) in top
        )

        log.info(
            "[infura-credits] est_billed=%s credits | rate=%.1f credits/h (%.3f credits/s) | req_sent=%s | top=%s",
            int(credits), cph, cps, self._rpc_requests_sent, top_s or "-",
        )

    def call(self, method: str, params: list[Any]) -> Any:
        """JSON-RPC call with resilient handling of HTTP 429/5xx.

        - Retry on HTTP 429 and 5xx with exponential backoff (+ jitter).
        - Respect Retry-After when present.
        - Some providers return rate limit as JSON-RPC error with HTTP 200.
        """
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}

        if self.session is None:
            self.session = requests.Session()

        last_err: Exception | None = None

        for attempt in range(1, RPC_HTTP_MAX_RETRIES + 2):  # retries + first try
            try:
                self._note_rpc_attempt(method)
                r = self.session.post(self.url, json=payload, timeout=self.timeout)

                # Handle rate limit / transient HTTP issues before raise_for_status()
                if r.status_code == 429 or r.status_code >= 500:
                    ra = None
                    try:
                        ra = r.headers.get("Retry-After")
                    except Exception:
                        ra = None

                    if attempt <= RPC_HTTP_MAX_RETRIES:
                        if ra:
                            try:
                                sleep_s = float(ra)
                            except Exception:
                                sleep_s = RPC_HTTP_BACKOFF_BASE_S * (2 ** (attempt - 1))
                        else:
                            sleep_s = RPC_HTTP_BACKOFF_BASE_S * (2 ** (attempt - 1))

                        sleep_s = min(float(RPC_HTTP_BACKOFF_CAP_S), float(sleep_s))
                        log.warning(
                            "rpc http %s for %s: retry in %.2fs (attempt %s/%s)",
                            r.status_code, method, sleep_s, attempt, RPC_HTTP_MAX_RETRIES + 1
                        )
                        _sleep_jitter(sleep_s)
                        continue

                    raise RpcHttpStatusError(status_code=r.status_code, url=self.url)

                self._note_rpc_billed_estimate(method, status_code=r.status_code)
                self._maybe_log_rpc_credits()

                r.raise_for_status()

                try:
                    j = r.json()
                except Exception as e:
                    body = ""
                    try:
                        body = (r.text or "")
                    except Exception:
                        body = ""
                    head = re.sub(r"\s+", " ", body[:220]).strip()
                    raise RuntimeError(
                        f"RPC batch JSON decode failed: {type(e).__name__}: {str(e)[:120]} "
                        f"(status={getattr(r,'status_code','?')}, body_head={head})"
                    )

                if "error" in j and j["error"]:
                    err = j["error"]
                    msg = str(err)
                    # eth_getLogs provider limit (>10k logs) is deterministic; don't retry.
                    if _is_jsonrpc_too_many_results(err):
                        raise RpcTooManyResultsError(f"RPC error (method={method}): {err}")
                    if attempt <= RPC_HTTP_MAX_RETRIES and (
                        ("rate" in msg.lower() and "limit" in msg.lower())
                        or ("too many requests" in msg.lower())
                    ):
                        sleep_s = min(
                            float(RPC_HTTP_BACKOFF_CAP_S),
                            RPC_HTTP_BACKOFF_BASE_S * (2 ** (attempt - 1))
                        )
                        log.warning(
                            "rpc json error looks like rate limit for %s: retry in %.2fs (attempt %s/%s)",
                            method, sleep_s, attempt, RPC_HTTP_MAX_RETRIES + 1
                        )
                        _sleep_jitter(sleep_s)
                        continue
                    raise RuntimeError(f"RPC error (method={method}): {err}")

                return j.get("result")

            except RpcHttpStatusError:
                raise
            except Exception as e:
                last_err = e
                if isinstance(e, RpcTooManyResultsError):
                    # Caller will split the range; retrying same request is wasteful.
                    raise
                if attempt <= RPC_HTTP_MAX_RETRIES:
                    sleep_s = min(float(RPC_HTTP_BACKOFF_CAP_S), RPC_HTTP_BACKOFF_BASE_S * (2 ** (attempt - 1)))
                    log.warning(
                        "rpc call failed for %s: %s -> retry in %.2fs (attempt %s/%s)",
                        method, str(e)[:200], sleep_s, attempt, RPC_HTTP_MAX_RETRIES + 1
                    )
                    _sleep_jitter(sleep_s)
                    continue
                break

        raise RuntimeError(f"RPC call failed after retries (method={method}): {last_err}")
    
    def batch_call(self, calls: List[Tuple[str, list[Any]]]) -> List[Any]:
        """JSON-RPC batch call.

        Many providers (incl. Infura) support HTTP batching: payload is a JSON array.
        This is useful when we need many lightweight calls (e.g. ERC20 balanceOf).

        Returns results in the same order as `calls`.
        """
        if not calls:
            return []

        if self.session is None:
            self.session = requests.Session()

        payload: List[Dict[str, Any]] = [
            {"jsonrpc": "2.0", "id": i + 1, "method": m, "params": p}
            for i, (m, p) in enumerate(calls)
        ]

        last_err: Exception | None = None

        for attempt in range(1, RPC_HTTP_MAX_RETRIES + 2):
            try:
                # credits telemetry: count each element as a separate request attempt
                for (m, _p) in calls:
                    self._note_rpc_attempt(m)

                r = self.session.post(self.url, json=payload, timeout=self.timeout)

                # Handle rate limit / transient HTTP issues
                if r.status_code == 429 or r.status_code >= 500:
                    ra = None
                    try:
                        ra = r.headers.get("Retry-After")
                    except Exception:
                        ra = None

                    if attempt <= RPC_HTTP_MAX_RETRIES:
                        if ra:
                            try:
                                sleep_s = float(ra)
                            except Exception:
                                sleep_s = RPC_HTTP_BACKOFF_BASE_S * (2 ** (attempt - 1))
                        else:
                            sleep_s = RPC_HTTP_BACKOFF_BASE_S * (2 ** (attempt - 1))

                        sleep_s = min(float(RPC_HTTP_BACKOFF_CAP_S), float(sleep_s))
                        log.warning(
                            "rpc batch http %s: retry in %.2fs (attempt %s/%s)",
                            r.status_code,
                            sleep_s,
                            attempt,
                            RPC_HTTP_MAX_RETRIES + 1,
                        )
                        _sleep_jitter(sleep_s)
                        continue

                    raise RpcHttpStatusError(status_code=r.status_code, url=self.url)

                # billing estimate: count each element (best-effort)
                for (m, _p) in calls:
                    self._note_rpc_billed_estimate(m, status_code=r.status_code)
                self._maybe_log_rpc_credits()

                r.raise_for_status()

                j = r.json()
                if not isinstance(j, list):
                    raise RuntimeError(f"RPC batch response is not a list: {type(j).__name__}")

                by_id: Dict[int, Any] = {}
                for item in j:
                    try:
                        _id = int(item.get("id") or 0)
                    except Exception:
                        _id = 0
                    by_id[_id] = item

                out: List[Any] = []
                for idx, (m, _p) in enumerate(calls, start=1):
                    item = by_id.get(idx) or {}
                    if "error" in item and item["error"]:
                        err = item["error"]
                        if _is_jsonrpc_too_many_results(err):
                            raise RpcTooManyResultsError(f"RPC error (method={m}): {err}")
                        raise RuntimeError(f"RPC error (method={m}): {err}")
                    out.append(item.get("result"))
                return out

            except RpcHttpStatusError:
                raise
            except Exception as e:
                last_err = e
                if attempt <= RPC_HTTP_MAX_RETRIES:
                    sleep_s = min(float(RPC_HTTP_BACKOFF_CAP_S), RPC_HTTP_BACKOFF_BASE_S * (2 ** (attempt - 1)))
                    log.warning(
                        "rpc batch call failed: %s -> retry in %.2fs (attempt %s/%s)",
                        str(e)[:200],
                        sleep_s,
                        attempt,
                        RPC_HTTP_MAX_RETRIES + 1,
                    )
                    _sleep_jitter(sleep_s)
                    continue
                break

        raise RuntimeError(f"RPC batch call failed after retries: {last_err}")


    def block_number(self) -> int:
        return _hex_to_int(self.call("eth_blockNumber", []))

    def get_block(self, block_number: int) -> Dict[str, Any]:
        return self.call("eth_getBlockByNumber", [_to_hex_block(block_number), False])

    def get_logs(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.call("eth_getLogs", [params]) or []

# ── ERC20 balance helpers (used by wallet enrichment) ───────────────────────

# Polymarket CLOB V2 collateral token on Polygon.
# Since CLOB V2 migration, trading balance should be read from pUSD, not legacy Polygon USDC.e.
# Official pUSD proxy:
#   0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB
DEFAULT_POLYMARKET_COLLATERAL_TOKEN = (
    os.getenv("POLYMARKET_COLLATERAL_TOKEN_ADDRESS")
    or os.getenv("POLYMARKET_PUSD_TOKEN_ADDRESS")
    or "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
).strip().lower()

# Backward-compatible name: existing callers still use fetch_usdc_balances_polygon_batch(...),
# but the token is now Polymarket collateral, i.e. pUSD.
DEFAULT_POLYGON_USDC_TOKEN = DEFAULT_POLYMARKET_COLLATERAL_TOKEN

_BALANCE_OF_SELECTOR = "0x70a08231"  # keccak256("balanceOf(address)")[:4]

def _normalize_address(addr: str) -> str:
    a = (addr or "").strip().lower()
    if not a:
        return ""
    if a.startswith("0x"):
        a = a[2:]
    a = a[-40:]
    return "0x" + a.zfill(40)


def _erc20_balance_of_calldata(wallet: str) -> str:
    w = _normalize_address(wallet)
    if not w:
        return _BALANCE_OF_SELECTOR + ("0" * 64)
    return _BALANCE_OF_SELECTOR + ("0" * 24) + w[2:]


def fetch_erc20_balances_batch(
    rpc: RpcClient,
    *,
    token_address: str,
    wallets: List[str],
    block_tag: str = "latest",
) -> Dict[str, int]:
    """Fetch ERC20 balances for a list of wallets using JSON-RPC batching.

    Returns mapping wallet->raw_balance (token smallest units).
    Unknown/failed balances are omitted from the result.
    """
    tok = _normalize_address(token_address)
    if not tok or not wallets:
        return {}

    calls: List[Tuple[str, list[Any]]] = []
    norm_wallets: List[str] = []
    for w in wallets:
        nw = _normalize_address(w)
        if not nw:
            continue
        norm_wallets.append(nw)
        calls.append(("eth_call", [{"to": tok, "data": _erc20_balance_of_calldata(nw)}, block_tag]))

    if not calls:
        return {}

    results = rpc.batch_call(calls)
    out: Dict[str, int] = {}
    for w, res in zip(norm_wallets, results):
        if not isinstance(res, str) or not res.startswith("0x"):
            continue
        try:
            out[w] = int(res, 16)
        except Exception:
            continue
    return out

def fetch_usdc_balances_polygon_batch(
    *,
    rpc_url: str,
    wallets: List[str],
    token_address: Optional[str] = None,
    timeout_s: float = DEFAULT_RPC_TIMEOUT_S,
) -> Dict[str, int]:
    """Convenience helper: fetch Polymarket collateral balances on Polygon.

    In CLOB V2 this is pUSD by default. Function name is kept for backward compatibility.
    """
    url = (rpc_url or "").strip()
    if not url:
        return {}
    tok = (token_address or DEFAULT_POLYGON_USDC_TOKEN or "").strip().lower()
    if not tok:
        return {}
    rpc = RpcClient(url=url, timeout=float(timeout_s))
    return fetch_erc20_balances_batch(rpc, token_address=tok, wallets=wallets)


class BlockTimestampCache:
    def __init__(self, rpc: RpcClient, max_size: int = 5000):
        self.rpc = rpc
        self.max_size = max_size
        self._cache: Dict[int, int] = {}
        self._order: List[int] = []

    def get(self, block_number: int) -> int:
        ts = self._cache.get(block_number)
        if ts is not None:
            return ts
        b = self.rpc.get_block(block_number)
        ts = _hex_to_int(b["timestamp"])
        self._cache[block_number] = ts
        self._order.append(block_number)
        if len(self._order) > self.max_size:
            old = self._order.pop(0)
            self._cache.pop(old, None)
        return ts

def find_block_by_timestamp(rpc: RpcClient, target_ts: int, *, confirmations: int = 0) -> int:
    """Find the greatest block with timestamp <= target_ts using binary search.

    We start from latest and bracket the target with a coarse estimate, then binary search.
    """
    latest = rpc.block_number()
    latest = max(0, latest - max(0, confirmations))
    cache = BlockTimestampCache(rpc, max_size=1000)
    latest_ts = cache.get(latest)

    # if target is in the future, return latest
    if target_ts >= latest_ts:
        return latest

    # Coarse estimate: Polygon ~2s/block, but we keep it conservative
    delta = max(1, int((latest_ts - target_ts) / DEFAULT_AVG_BLOCK_TIME_S))
    lo = max(0, latest - delta - 2000)  # widen the bracket
    hi = latest

    # ensure lo is not after target
    try:
        lo_ts = cache.get(lo)
    except Exception:
        lo_ts = 0

    if lo_ts > target_ts:
        # expand further back exponentially
        step = max(5000, delta)
        while lo > 0 and lo_ts > target_ts:
            hi = lo
            lo = max(0, lo - step)
            lo_ts = cache.get(lo)
            step *= 2

    # binary search [lo, hi]
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        mid_ts = cache.get(mid)
        if mid_ts <= target_ts:
            lo = mid
        else:
            hi = mid

    return lo

def decode_order_filled_log(log_item: Dict[str, Any]) -> Dict[str, Any]:
    """Decode a CLOB V2 eth_getLogs entry into a subgraph-like OrderFilled event dict.

    V2 emits:
      OrderFilled(orderHash, maker, taker, side, tokenId,
                  makerAmountFilled, takerAmountFilled, fee, builder, metadata)

    Downstream code still expects legacy-like makerAssetId/takerAssetId, so we derive:
      side=0 BUY  -> makerAssetId=0,       takerAssetId=tokenId
      side=1 SELL -> makerAssetId=tokenId, takerAssetId=0
    """
    topics = log_item.get("topics") or []
    data = log_item.get("data") or "0x"
    if not topics or topics[0].lower() != ORDER_FILLED_TOPIC0.lower():
        raise ValueError("Not an OrderFilled log")

    # Expected indexed params:
    # topic1 = orderHash (bytes32)
    # topic2 = maker (address)
    # topic3 = taker (address)
    if len(topics) < 4:
        raise ValueError(f"Unexpected topics length for OrderFilled: {len(topics)}")

    order_hash = _topic_to_bytes32(topics[1])
    maker = _topic_to_address(topics[2])
    taker = _topic_to_address(topics[3])

    words = _data_words(data)
    # side, tokenId, makerAmountFilled, takerAmountFilled, fee, builder, metadata
    if len(words) < 7:
        raise ValueError(f"Unexpected data words for OrderFilled: {len(words)}")

    side = _word_to_int(words[0])
    token_id = _word_to_int(words[1])
    maker_amount_filled = _word_to_int(words[2])
    taker_amount_filled = _word_to_int(words[3])
    fee = _word_to_int(words[4])
    builder = words[5]
    metadata = words[6]

    if side not in (0, 1):
        raise ValueError(f"Unexpected OrderFilled side={side}")

    # CLOB V2 convention:
    #   side=0 BUY  -> maker pays collateral (asset 0), taker receives tokenId
    #   side=1 SELL -> maker sells tokenId, taker pays collateral (asset 0)
    maker_asset_id = side * token_id
    taker_asset_id = token_id - maker_asset_id

    tx_hash = log_item.get("transactionHash")
    log_index = _hex_to_int(log_item.get("logIndex", "0x0"))
    block_number = _hex_to_int(log_item.get("blockNumber", "0x0"))

    # Best-effort: per-wallet USDC/pUSD deltas in *micro* units (same scale as amounts in the event).
    # This lets callers update cached balances without needing extra subgraph calls.
    # Convention: positive => wallet receives collateral, negative => wallet spends collateral.
    usdc_deltas: Dict[str, int] = {}
    if maker_asset_id == 0:
        # maker gives collateral, taker receives collateral
        usdc_deltas[maker.lower()] = usdc_deltas.get(maker.lower(), 0) - int(maker_amount_filled)
        usdc_deltas[taker.lower()] = usdc_deltas.get(taker.lower(), 0) + int(maker_amount_filled)
    elif taker_asset_id == 0:
        # taker gives collateral, maker receives collateral
        usdc_deltas[taker.lower()] = usdc_deltas.get(taker.lower(), 0) - int(taker_amount_filled)
        usdc_deltas[maker.lower()] = usdc_deltas.get(maker.lower(), 0) + int(taker_amount_filled)

    # Subgraph-compatible keys (as used in existing ingest)
    return {
        "id": f"{tx_hash}:{log_index}",
        "exchangeAddress": (str(log_item.get("address") or "")).lower() or None,
        "transactionHash": tx_hash,
        "orderHash": order_hash,
        "maker": maker,
        "taker": taker,
        "sideRaw": side,
        "tokenId": token_id,
        "makerAssetId": maker_asset_id,
        "takerAssetId": taker_asset_id,
        "makerAmountFilled": maker_amount_filled,
        "takerAmountFilled": taker_amount_filled,
        "fee": fee,
        "builder": builder,
        "metadata": metadata,
        "blockNumber": block_number,
        "logIndex": log_index,
        "topic0": topics[0].lower(),
        "topics": topics,
        "data": data,
        # Extra raw log metadata (optional; useful for debugging / ordering)
        "blockHash": (str(log_item.get("blockHash") or "")).lower() or None,
        "transactionIndex": _hex_to_int(log_item.get("transactionIndex", "0x0")),
        "removed": bool(log_item.get("removed", False)),
        "usdc_deltas": usdc_deltas,
    }

def iter_order_filled_events_since_ts(
    *,
    rpc_url: str,
    from_ts: int,
    start_block: Optional[int] = None,
    progress: Optional[Dict[str, Any]] = None,
    page_size: int = 1000,
    max_pages: int = 30,
    confirmations: int = DEFAULT_CONFIRMATIONS,
    chunk_blocks: int = DEFAULT_CHUNK_BLOCKS,
    addresses: Optional[List[str]] = None,
) -> Iterable[List[Dict[str, Any]]]:
    """Yield pages (lists) of decoded OrderFilled events since from_ts (unix seconds)."""
    # keep env minimal: timeout is internal default; override only by passing RpcClient if needed later
    rpc = RpcClient(rpc_url, timeout=DEFAULT_RPC_TIMEOUT_S)
    cache = BlockTimestampCache(rpc, max_size=5000)

    addrs = addresses or DEFAULT_EXCHANGE_ADDRESSES
    addrs = [a.lower() for a in addrs]

    log.info(
        "[rpc-fills] using exchange addresses: %s | topic0=%s",
        ",".join(addrs),
        ORDER_FILLED_TOPIC0,
    )

    # If caller already knows an approximate start block (saved watermark), skip costly timestamp->block search.
    if start_block is None:
        start_block = find_block_by_timestamp(rpc, from_ts, confirmations=confirmations)
        start_src = "ts->block"
    else:
        start_block = max(0, int(start_block))
        start_src = "watermark"
    latest = rpc.block_number()
    latest = max(0, latest - max(0, confirmations))

    if progress is not None:
        progress["start_block"] = start_block
        progress["latest_block"] = latest
        progress["max_event_block"] = None
        progress["max_event_ts"] = None
        progress["last_scanned_block"] = None

    log.info(
        "[rpc-fills] scan blocks: start=%s latest=%s (from_ts=%s conf=%s chunk=%s src=%s)",
        start_block, latest, from_ts, confirmations, chunk_blocks, start_src,
    )

    buf: List[Dict[str, Any]] = []
    pages = 0

    b = start_block
    while b <= latest and pages < max_pages:
        # chunk_blocks is only a starting window; if the provider says "too many results",
        # _get_logs_adaptive will split it until it fits.
        to_b = min(latest, b + max(1, int(chunk_blocks)) - 1)
        if progress is not None:
            progress["last_scanned_block"] = to_b
        logs = _get_logs_adaptive(
            rpc,
            from_block=b,
            to_block=to_b,
            addresses=addrs,
            topic0=ORDER_FILLED_TOPIC0,
            progress=progress,
        )
        _memlog("chunk_logs_loaded", from_block=b, to_block=to_b, logs_len=len(logs))

        if logs:
            # Ensure deterministic order
            logs.sort(key=lambda x: (_hex_to_int(x.get("blockNumber", "0x0")), _hex_to_int(x.get("logIndex", "0x0"))))
            decoded_cnt = 0
            for li in logs:
                ev = decode_order_filled_log(li)
                # Attach timestamp (needed by downstream). Cache block timestamps.
                ev["timestamp"] = cache.get(ev["blockNumber"])
                decoded_cnt += 1
                # Respect from_ts watermark at event level (eth_getLogs is block-based).
                if int(ev["timestamp"]) < int(from_ts):
                    continue
                if progress is not None:
                    cur_max_ts = progress.get("max_event_ts")
                    if cur_max_ts is None or int(ev["timestamp"]) > int(cur_max_ts):
                        progress["max_event_ts"] = int(ev["timestamp"]) 
                        progress["max_event_block"] = int(ev["blockNumber"]) 
                buf.append(ev)

                if len(buf) >= page_size:
                    pages += 1
                    _memlog("page_yield", page_size=page_size, buf_len=len(buf))
                    yield buf[:page_size]
                    buf = buf[page_size:]
                    if pages >= max_pages:
                        break

            _memlog(
                "chunk_decoded",
                from_block=b,
                to_block=to_b,
                decoded_cnt=decoded_cnt,
                buf_len=len(buf),
            )

        try:
            del logs
        except Exception:
            pass
        gc.collect()
        _memlog("chunk_after_gc", from_block=b, to_block=to_b, buf_len=len(buf))

        b = to_b + 1

    # flush remainder
    if buf and pages < max_pages:
        yield buf

def parse_exchange_addresses_env(env_val: str | None) -> Optional[List[str]]:
    if not env_val:
        return None
    parts = [p.strip() for p in env_val.split(",") if p.strip()]
    if not parts:
        return None
    return parts
