#news_trade/trade_from_extracted_values_worker.py

from __future__ import annotations

import os
import json
import time
from time import monotonic
from datetime import datetime, timezone, timedelta
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import select, update, func
from sqlalchemy.sql import text as sql_text

from common.db import get_session
from common.logger import get_logger
from common.telegram_utils import send_ingest_summary_sync, send_message_to_chat_sync
from news_trade.eps_orders import (
    place_trade_for_decision,
    build_batch_order_for_decision,
    place_trades_batch_for_account,
)
from news_trade.eps_trade_finalize import (
    build_order_placed_message,
    send_telegram_sync,
)

# IMPORTANT:
# These imports are needed so SQLAlchemy registry knows relationship targets
# used by ExtractedValue: relationship("Company") and relationship("IngestedDoc").
# Without them, mapper configuration may fail with "failed to locate a name ('Company')".
from models.t_companies import Company  # noqa: F401
from models.t_ingested_docs import IngestedDoc  # noqa: F401
from models.t_extracted_values import ExtractedValue
from models.t_monitored_news import MonitoredNews
from models.t_news_trade_confirmations import NewsTradeConfirmation  # noqa: F401

logger = get_logger(__name__)
PrimarySession = get_session("primary")
_LAST_IDLE_LOG = 0.0

def _deactivate_subscription(sub_id: int, reason: str | None = None) -> None:
    """
    One-shot rules: deactivate monitored_news after it fired (success) OR was skipped.
    """
    with PrimarySession() as s:
        q = (
            update(MonitoredNews)
            .where(MonitoredNews.id == int(sub_id))
            .values(status="inactive", updated_at=func.now())
        )
        res = s.execute(q)
        s.commit()
        logger.info("sub_deactivated: sub_id=%s rowcount=%s reason=%s", sub_id, int(res.rowcount or 0), reason)


def _notify_extracted_value(
    *,
    ev: dict[str, Any],
    subs: list[dict[str, Any]],
    reason: str,
) -> None:
    """
    Telegram notify about extracted_values processing.

    - If there are subscriptions: send to each sub.tg_chat_id (deduped).
    - If no subscriptions: send to TELEGRAM_INGEST_CHAT_ID via send_ingest_summary_sync().
    Controlled by env TG_NOTIFY_EXTRACTED=1.
    """
    if os.getenv("TG_NOTIFY_EXTRACTED", "0").strip() != "1":
        return

    try:
        ticker = str(ev.get("ticker") or "").strip().upper()
        metric_key = str(ev.get("metric_key") or "").strip()
        value = ev.get("value_num")
        ingest_id = ev.get("ingest_id")
        conf = ev.get("confidence")

        evidence = ev.get("evidence") or {}
        url = evidence.get("url") or ""

        # Compact JSON preview (optional, avoids huge payloads)
        evidence_preview = ""
        try:
            if evidence:
                evidence_preview = json.dumps(evidence, ensure_ascii=False)[:600]
        except Exception:
            evidence_preview = ""

        header = "📥 extracted_value"
        lines = [
            header,
            f"ticker: {ticker}",
            f"metric: {metric_key}",
            f"value: {value}",
            f"confidence: {conf}",
            f"ingest_id: {ingest_id}",
            f"reason: {reason}",
        ]
        if url:
            lines.append(f"url: {url}")
        if evidence_preview:
            lines.append(f"evidence: {evidence_preview}")

        text = "\n".join(lines)

        # 1) Send to subscriptions chat_ids (if any)
        chat_ids: set[str] = set()
        for s in subs or []:
            cid = s.get("tg_chat_id")
            if cid is None:
                continue
            chat_ids.add(str(cid))

        if chat_ids:
            for cid in sorted(chat_ids):
                send_message_to_chat_sync(chat_id=cid, text=text, parse_mode=None)
            return

        # 2) No subscriptions -> optionally suppress fallback for service metrics
        silent_if_no_subs = {
            "bcb_selic_target",
        }
        if metric_key in silent_if_no_subs:
            logger.info(
                "tg notify extracted_value skipped: no_subscriptions metric=%s ticker=%s",
                metric_key,
                ticker,
            )
            return

        # 3) No subscriptions -> send to TELEGRAM_INGEST_CHAT_ID
        send_ingest_summary_sync(text, parse_mode=None)

    except Exception as e:
        logger.warning("tg notify extracted_value failed: %s", e)

def _reset_stuck_processing(minutes: int = 10) -> int:
    with PrimarySession() as s:
        q = (
            update(ExtractedValue)
            .where(
                ExtractedValue.trade_status == "PROCESSING",
                ExtractedValue.trade_updated_at < (func.now() - sql_text(f"interval '{int(minutes)} minutes'")),
            )
            .values(trade_status="NEW", trade_error="reset_stuck_processing", trade_updated_at=func.now())
        )
        res = s.execute(q)
        s.commit()
        n = int(res.rowcount or 0)
        if n:
            logger.warning("reset_stuck_processing: reset=%s rows", n)
        return n


def _claim_batch(limit: int) -> list[dict[str, Any]]:
    """
    Atomically claim NEW extracted_values -> PROCESSING using SKIP LOCKED.
    Returns lightweight dict rows.
    """
    with PrimarySession() as s:
        q = sql_text(
            """
            WITH cte AS (
              SELECT id
              FROM extracted_values
              WHERE trade_status = 'NEW'
              ORDER BY id ASC
              FOR UPDATE SKIP LOCKED
              LIMIT :limit
            )
            UPDATE extracted_values ev
            SET trade_status = 'PROCESSING',
                trade_updated_at = now()
            FROM cte
            WHERE ev.id = cte.id
            RETURNING
              ev.id, ev.company_id, ev.ingest_id, ev.ticker, ev.metric_key,
              ev.value_num, ev.value_raw, ev.confidence, ev.evidence, ev.created_at;
            """
        )
        # NOTE: no logging here; run_once() decides when to log to avoid idle spam.
        rows = s.execute(q, {"limit": int(limit)}).mappings().all()
        s.commit()
        return [dict(r) for r in rows]

def _set_trade_status(ev_id: int, status: str, err: str | None = None) -> None:
    with PrimarySession() as s:
        s.execute(
            update(ExtractedValue)
            .where(ExtractedValue.id == int(ev_id))
            .values(trade_status=status, trade_error=err, trade_updated_at=func.now())
        )
        s.commit()

def _resolve_order_price_for_action(sub: dict[str, Any], action: str) -> float | None:
    params = sub.get("params") or {}

    key = "order_price_yes" if str(action).upper() == "YES" else "order_price_no"
    v = params.get(key)
    if v is not None:
        try:
            return float(v)
        except Exception:
            logger.warning(
                "bad %s for sub_id=%s value=%r; fallback to order_price",
                key,
                sub.get("id"),
                v,
            )

    return sub.get("order_price")

def _load_subscriptions(
    ticker: str,
    metric_key: str,
    execution_path: str | None = None,
) -> list[dict[str, Any]]:
    """
    Find active monitored_news that want this metric.
    Convention:
      - monitored_news.params.metric_key == extracted.metric_key
      - monitored_news.params.execution_path in {"poll","fast"}; default is "poll"
    """
    with PrimarySession() as s:
        stmt = (
            select(
                MonitoredNews.id,
                MonitoredNews.rule_key,
                MonitoredNews.params,
                MonitoredNews.tg_chat_id,
                MonitoredNews.account_name,
                MonitoredNews.condition_id,
                MonitoredNews.question,
                MonitoredNews.order_qty,
                MonitoredNews.order_price,
            )
            .where(
                MonitoredNews.status == "active",
                MonitoredNews.ticker == ticker,
                MonitoredNews.params["metric_key"].astext == metric_key,
            )
        )

        if execution_path:
            stmt = stmt.where(
                func.coalesce(MonitoredNews.params["execution_path"].astext, "poll") == execution_path
            )

        rows = (
            s.execute(
                stmt.order_by(MonitoredNews.priority.asc(), MonitoredNews.id.asc())
            )
            .all()
        )

    out: list[dict[str, Any]] = []
    for r in rows:
        row_id = int(r[0])
        rule_key = str(r[1] or "default")
        params = r[2] or {}
        out.append(
            {
                "id": row_id,
                "rule_key": rule_key,
                "params": params,
                "tg_chat_id": r[3],
                "account_name": r[4],
                "condition_id": r[5],
                "question": r[6],
                "order_qty": float(r[7]) if r[7] is not None else None,
                "order_price": float(r[8]) if r[8] is not None else None,
            }
        )
    return out

def _notify_trade_quarantine(
    *,
    sub: dict[str, Any],
    ev: dict[str, Any],
    reason: str,
    value: float,
    threshold: float,
    op: str,
    execution_path: str,
) -> None:
    """
    Alert when a live-capable rule is blocked by the safety gate.
    Controlled by TG_NOTIFY_TRADE_QUARANTINE=1, default enabled because this is a risk control.
    """
    if os.getenv("TG_NOTIFY_TRADE_QUARANTINE", "1").strip() != "1":
        return

    chat_id = sub.get("tg_chat_id")
    if chat_id is None:
        return

    try:
        evidence = ev.get("evidence") or {}
        parsed = evidence.get("parsed") or {}
        url = evidence.get("url") or ""

        lines = [
            "🚫 TRADE QUARANTINED",
            f"ticker: {str(ev.get('ticker') or '').strip().upper()}",
            f"metric: {str(ev.get('metric_key') or '').strip()}",
            f"value: {value}",
            f"condition: value {op} {threshold}",
            f"rule: {sub.get('rule_key')}",
            f"account: {sub.get('account_name')}",
            f"path: {execution_path}",
            f"ingest_id: {ev.get('ingest_id')}",
            f"reason: {reason}",
        ]
        if url:
            lines.append(f"url: {url}")
        if parsed:
            try:
                lines.append("parsed: " + json.dumps(parsed, ensure_ascii=False)[:1000])
            except Exception:
                lines.append(f"parsed: {parsed!r}"[:1000])

        send_message_to_chat_sync(chat_id=str(chat_id), text="\n".join(lines), parse_mode=None)
    except Exception:
        logger.exception(
            "trade quarantine tg failed sub_id=%s ev_id=%s",
            sub.get("id"),
            ev.get("id"),
        )



def _mstr_trade_safety_ok(
    ev: dict[str, Any],
    value: float,
    sub: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """
    Fail-closed safety gate for MSTR BTC metrics.

    Base checks:
      - extractor evidence must be kind=mstr_btc_update;
      - parsed.validation_ok must be True;
      - the extracted value must exactly match the validated parsed field.

    Optional rule-level cross-check via monitored_news.params:
      - previous_btc_holdings / expected_previous_btc_holdings / mstr_previous_btc_holdings
      - holdings_delta_tolerance / mstr_holdings_delta_tolerance, default 0

    If previous holdings is supplied, require:
        parsed.btc_holdings == previous_btc_holdings + parsed.btc_acquired

    This protects both acquired-BTC rules and holdings rules from internally
    inconsistent MSTR filings/parses.
    """
    ticker = str(ev.get("ticker") or "").strip().upper()
    metric_key = str(ev.get("metric_key") or "").strip()

    if ticker != "MSTR":
        return True, None

    if metric_key not in {"mstr_btc_acquired", "mstr_btc_holdings"}:
        return True, None

    evidence = ev.get("evidence") or {}
    parsed = evidence.get("parsed") or {}

    if evidence.get("kind") != "mstr_btc_update":
        return False, "mstr_missing_kind_mstr_btc_update"

    if not isinstance(parsed, dict):
        return False, "mstr_parsed_not_dict"

    if parsed.get("validation_ok") is not True:
        return False, f"mstr_validation_not_ok errors={parsed.get('validation_errors')}"

    expected_field = "btc_acquired" if metric_key == "mstr_btc_acquired" else "btc_holdings"
    parsed_value = parsed.get(expected_field)
    if parsed_value is None:
        return False, f"mstr_missing_validated_field field={expected_field}"

    try:
        if float(parsed_value) != float(value):
            return False, f"mstr_value_mismatch field={expected_field} parsed={parsed_value} value={value}"
    except Exception:
        return False, f"mstr_bad_parsed_value field={expected_field} parsed={parsed_value} value={value}"

    params = (sub or {}).get("params") or {}
    prev_raw = (
        params.get("previous_btc_holdings")
        if params.get("previous_btc_holdings") is not None
        else params.get("expected_previous_btc_holdings")
    )
    if prev_raw is None:
        prev_raw = params.get("mstr_previous_btc_holdings")

    if prev_raw is not None:
        try:
            prev_holdings = int(float(prev_raw))
            acquired = int(float(parsed.get("btc_acquired")))
            holdings = int(float(parsed.get("btc_holdings")))
        except Exception:
            return (
                False,
                "mstr_holdings_crosscheck_bad_inputs "
                f"prev={prev_raw} acquired={parsed.get('btc_acquired')} holdings={parsed.get('btc_holdings')}",
            )

        tol_raw = (
            params.get("holdings_delta_tolerance")
            if params.get("holdings_delta_tolerance") is not None
            else params.get("mstr_holdings_delta_tolerance")
        )
        try:
            tolerance = int(float(tol_raw)) if tol_raw is not None else 0
        except Exception:
            tolerance = 0

        expected_holdings = prev_holdings + acquired
        diff = holdings - expected_holdings
        if abs(diff) > tolerance:
            return (
                False,
                "mstr_holdings_crosscheck_failed "
                f"prev={prev_holdings} acquired={acquired} expected={expected_holdings} "
                f"parsed_holdings={holdings} diff={diff} tolerance={tolerance}",
            )

    return True, None


def _manual_confirm_enabled(params: dict[str, Any]) -> bool:
    v = (
        params.get("manual_confirm_enabled")
        if params.get("manual_confirm_enabled") is not None
        else params.get("confirm_enabled")
    )
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _first_param(params: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if params.get(k) is not None:
            return params.get(k)
    return None


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    try:
        import decimal
        if isinstance(obj, decimal.Decimal):
            return float(obj)
    except Exception:
        pass
    return str(obj)


def _assert_news_trade_confirmations_table_exists() -> None:
    """
    Runtime guard only.

    The table must be created explicitly by SQL migration before the workers run.
    We intentionally do not CREATE TABLE here: trading code should fail loudly
    if the confirmation queue schema is missing or deployed incorrectly.
    """
    with PrimarySession() as s:
        exists = s.execute(
            sql_text("SELECT to_regclass('news_trade_confirmations') IS NOT NULL")
        ).scalar()

    if not exists:
        raise RuntimeError(
            "Missing table news_trade_confirmations. Apply the SQL migration before running confirmations."
        )

def _create_manual_trade_confirmation_if_needed(
    *,
    sub: dict[str, Any],
    sub_for_trade: dict[str, Any],
    ev: dict[str, Any],
    action: str,
    value: float,
    threshold: float,
    op: str,
    execution_path: str,
    auto_trade: dict[str, Any] | None = None,
) -> int | None:
    """
    Create a pending manual-confirmation trade.

    Rule config lives in monitored_news.params. Suggested params:
      {
        "manual_confirm_enabled": true,
        "manual_confirm_order_qty": 5000,
        "manual_confirm_order_price": 0.99,
        "manual_confirm_account_name": "kinderSman",
        "manual_confirm_ttl_sec": 600
      }

    The normal monitored_news.order_qty/order_price can remain the small
    automatic order. The manual_confirm_* values define the larger order.
    """
    params = sub.get("params") or {}

    if not _manual_confirm_enabled(params):
        return None

    if os.getenv("TRADE_CONFIRMATIONS_ENABLED", "1").strip() != "1":
        logger.info(
            "manual confirmation skipped: TRADE_CONFIRMATIONS_ENABLED!=1 sub_id=%s ev_id=%s",
            sub.get("id"),
            ev.get("id"),
        )
        return None

    confirm_qty = _float_or_none(_first_param(
        params,
        "manual_confirm_order_qty",
        "confirm_order_qty",
        "large_order_qty",
    ))
    if confirm_qty is None or confirm_qty <= 0:
        logger.warning(
            "manual confirmation skipped: bad/missing confirm qty sub_id=%s ev_id=%s params=%r",
            sub.get("id"),
            ev.get("id"),
            params,
        )
        return None

    confirm_price = _float_or_none(_first_param(
        params,
        "manual_confirm_order_price",
        "confirm_order_price",
        "large_order_price",
    ))
    if confirm_price is None:
        confirm_price = _float_or_none(sub_for_trade.get("order_price"))

    confirm_account = str(
        _first_param(params, "manual_confirm_account_name", "confirm_account_name")
        or sub_for_trade.get("account_name")
        or sub.get("account_name")
        or ""
    ).strip() or None

    confirm_condition_id = str(
        _first_param(params, "manual_confirm_condition_id", "confirm_condition_id")
        or sub_for_trade.get("condition_id")
        or sub.get("condition_id")
        or ""
    ).strip() or None

    if confirm_price is None or confirm_price <= 0:
        logger.warning(
            "manual confirmation skipped: bad/missing confirm price sub_id=%s ev_id=%s params=%r",
            sub.get("id"),
            ev.get("id"),
            params,
        )
        return None

    manual_sub_for_trade = dict(sub_for_trade)
    manual_sub_for_trade["order_qty"] = float(confirm_qty)
    manual_sub_for_trade["order_price"] = float(confirm_price)
    if confirm_account:
        manual_sub_for_trade["account_name"] = confirm_account
    if confirm_condition_id:
        manual_sub_for_trade["condition_id"] = confirm_condition_id

    ev_id = int(ev["id"])
    sub_id = int(sub["id"])
    action_norm = str(action).upper()
    idempotency_key = f"manual_confirm:ev:{ev_id}:sub:{sub_id}:action:{action_norm}"

    ttl_sec_raw = _first_param(params, "manual_confirm_ttl_sec", "confirm_ttl_sec")
    try:
        ttl_sec = int(float(ttl_sec_raw)) if ttl_sec_raw is not None else 900
    except Exception:
        ttl_sec = 900
    ttl_sec = max(60, min(ttl_sec, 24 * 3600))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_sec)

    evidence = ev.get("evidence") or {}
    parsed = evidence.get("parsed") or {}
    source_url = evidence.get("url") or ""

    payload = {
        "sub_for_trade": manual_sub_for_trade,
        "action": action_norm,
        "ev": {
            "id": ev_id,
            "ingest_id": ev.get("ingest_id"),
            "ticker": ev.get("ticker"),
            "metric_key": ev.get("metric_key"),
            "value_num": ev.get("value_num"),
            "confidence": ev.get("confidence"),
            "evidence": evidence,
        },
        "decision": {
            "value": value,
            "op": op,
            "threshold": threshold,
            "execution_path": execution_path,
            "rule_key": sub.get("rule_key"),
        },
        "auto_trade": auto_trade or {},
    }

    _assert_news_trade_confirmations_table_exists()

    with PrimarySession() as s:
        row = s.execute(
            sql_text(
                """
                INSERT INTO news_trade_confirmations (
                    idempotency_key,
                    status,
                    expires_at,
                    ev_id,
                    ingest_id,
                    sub_id,
                    ticker,
                    metric_key,
                    execution_path,
                    action,
                    account_name,
                    condition_id,
                    question,
                    order_qty,
                    order_price,
                    tg_chat_id,
                    source_url,
                    payload
                )
                VALUES (
                    :idempotency_key,
                    'PENDING',
                    :expires_at,
                    :ev_id,
                    :ingest_id,
                    :sub_id,
                    :ticker,
                    :metric_key,
                    :execution_path,
                    :action,
                    :account_name,
                    :condition_id,
                    :question,
                    :order_qty,
                    :order_price,
                    :tg_chat_id,
                    :source_url,
                    CAST(:payload AS jsonb)
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """
            ),
            {
                "idempotency_key": idempotency_key,
                "expires_at": expires_at,
                "ev_id": ev_id,
                "ingest_id": ev.get("ingest_id"),
                "sub_id": sub_id,
                "ticker": str(ev.get("ticker") or "").strip().upper(),
                "metric_key": str(ev.get("metric_key") or "").strip(),
                "execution_path": execution_path,
                "action": action_norm,
                "account_name": confirm_account,
                "condition_id": confirm_condition_id,
                "question": sub.get("question"),
                "order_qty": confirm_qty,
                "order_price": confirm_price,
                "tg_chat_id": sub.get("tg_chat_id"),
                "source_url": source_url,
                "payload": json.dumps(payload, ensure_ascii=False, default=_json_safe),
            },
        ).first()
        s.commit()

    if not row:
        logger.info(
            "manual confirmation already exists idempotency_key=%s ev_id=%s sub_id=%s action=%s",
            idempotency_key,
            ev_id,
            sub_id,
            action_norm,
        )
        return None

    pending_id = int(row[0])

    logger.warning(
        "manual confirmation created id=%s sub_id=%s rule=%s account=%s ev_id=%s "
        "ticker=%s metric=%s action=%s qty=%s price=%s expires_at=%s",
        pending_id,
        sub_id,
        sub.get("rule_key"),
        confirm_account,
        ev_id,
        str(ev.get("ticker") or "").strip().upper(),
        str(ev.get("metric_key") or "").strip(),
        action_norm,
        confirm_qty,
        confirm_price,
        expires_at.isoformat(),
    )

    chat_id = sub.get("tg_chat_id")
    if chat_id is not None:
        lines = [
            "🟡 TRADE CONFIRM REQUIRED",
            f"id: {pending_id}",
            f"command: /confirm_trade {pending_id}",
            f"reject: /reject_trade {pending_id}",
            f"ticker: {str(ev.get('ticker') or '').strip().upper()}",
            f"metric: {str(ev.get('metric_key') or '').strip()}",
            f"value: {value}",
            f"condition: value {op} {threshold}",
            f"action: {action_norm}",
            f"rule: {sub.get('rule_key')}",
            f"account: {confirm_account}",
            f"qty: {confirm_qty}",
            f"price: {confirm_price}",
            f"ingest_id: {ev.get('ingest_id')}",
            f"expires_at_utc: {expires_at.isoformat()}",
        ]
        if source_url:
            lines.append(f"url: {source_url}")
        if parsed:
            try:
                lines.append("parsed: " + json.dumps(parsed, ensure_ascii=False)[:1000])
            except Exception:
                lines.append(f"parsed: {parsed!r}"[:1000])

        try:
            send_message_to_chat_sync(chat_id=str(chat_id), text="\n".join(lines), parse_mode=None)
        except Exception:
            logger.exception(
                "manual confirmation tg failed id=%s sub_id=%s ev_id=%s",
                pending_id,
                sub_id,
                ev_id,
            )

    return pending_id


def process_extracted_value(
    ev: dict[str, Any],
    *,
    execution_path: str,
    update_trade_status: bool,
) -> str:
    ev_id = int(ev["id"])
    ticker = str(ev.get("ticker") or "").strip().upper()
    metric_key = str(ev.get("metric_key") or "").strip()
    ingest_id = ev.get("ingest_id")
    value_num = ev.get("value_num")

    trade_enabled = os.getenv("TRADE_ENABLED", "0").strip() == "1"
    allow_without_ingest = os.getenv("ALLOW_TRADE_WITHOUT_INGEST", "0").strip() == "1"

    def _set(status: str, err: str | None = None) -> None:
        if update_trade_status:
            _set_trade_status(ev_id, status, err)

    # guards
    if (ingest_id is None) and (not allow_without_ingest):
        logger.info(
            "SKIP ev_id=%s ticker=%s metric=%s path=%s reason=no_ingest_id",
            ev_id, ticker, metric_key, execution_path
        )
        _set("SKIPPED", "no_ingest_id")
        return "SKIPPED"

    if value_num is None:
        logger.info(
            "SKIP ev_id=%s ticker=%s metric=%s path=%s reason=no_value",
            ev_id, ticker, metric_key, execution_path
        )
        _set("SKIPPED", "no_value")
        return "SKIPPED"

    value = float(value_num)
    subs = _load_subscriptions(ticker, metric_key, execution_path=execution_path)

    if not subs:
        logger.info(
            "SKIP ev_id=%s ticker=%s metric=%s path=%s reason=no_subscriptions value=%s",
            ev_id, ticker, metric_key, execution_path, value
        )
        _notify_extracted_value(ev=ev, subs=[], reason=f"no_subscriptions:{execution_path}")
        _set("SKIPPED", f"no_subscriptions:{execution_path}")
        return "SKIPPED"

    _notify_extracted_value(ev=ev, subs=subs, reason=f"has_subscriptions:{execution_path}")

    any_failed = False
    failed_notes: list[str] = []
    any_trade_attempt = False

    use_batch = trade_enabled and _should_use_batch_for_ev(
        ticker=ticker,
        metric_key=metric_key,
        execution_path=execution_path,
    )
    batch_groups: dict[str, list[dict[str, Any]]] = {}    

    for sub in subs:
        params = sub["params"] or {}
        threshold = params.get("threshold")
        op = params.get("cmp", ">=")

        if threshold is None:
            logger.info("SKIP sub_id=%s ev_id=%s path=%s reason=no_threshold", sub["id"], ev_id, execution_path)
            continue

        try:
            thr = float(threshold)
        except Exception:
            logger.info(
                "SKIP sub_id=%s ev_id=%s path=%s reason=bad_threshold threshold=%r",
                sub["id"], ev_id, execution_path, threshold
            )
            continue

        passed = _cmp(value, thr, op)

        safe_ok, safe_reason = _mstr_trade_safety_ok(ev, value, sub=sub)
        if not safe_ok:
            quarantine_reason = safe_reason or "safety_gate_failed"
            logger.error(
                "TRADE_QUARANTINED sub_id=%s rule=%s account=%s ev_id=%s ticker=%s "
                "metric=%s value=%s op=%s thr=%s ingest_id=%s path=%s reason=%s url=%s",
                sub["id"],
                sub.get("rule_key"),
                sub.get("account_name"),
                ev_id,
                ticker,
                metric_key,
                value,
                op,
                thr,
                ev.get("ingest_id"),
                execution_path,
                quarantine_reason,
                (ev.get("evidence") or {}).get("url"),
            )
            _notify_trade_quarantine(
                sub=sub,
                ev=ev,
                reason=quarantine_reason,
                value=value,
                threshold=thr,
                op=op,
                execution_path=execution_path,
            )
            continue

        decision_mode = str(params.get("decision_mode") or "binary_yes_no").strip().lower()

        if decision_mode == "yes_only":
            if not passed:
                logger.info(
                    "SKIP sub_id=%s rule=%s account=%s ev_id=%s ticker=%s metric=%s value=%s op=%s thr=%s ingest_id=%s path=%s reason=yes_only_not_passed url=%s",
                    sub["id"],
                    sub.get("rule_key"),
                    sub.get("account_name"),
                    ev_id,
                    ticker,
                    metric_key,
                    value,
                    op,
                    thr,
                    ev.get("ingest_id"),
                    execution_path,
                    (ev.get("evidence") or {}).get("url"),
                )
                continue
            action = "YES"

        elif decision_mode == "no_only":
            if not passed:
                logger.info(
                    "SKIP sub_id=%s rule=%s account=%s ev_id=%s ticker=%s metric=%s value=%s op=%s thr=%s ingest_id=%s path=%s reason=no_only_not_passed url=%s",
                    sub["id"],
                    sub.get("rule_key"),
                    sub.get("account_name"),
                    ev_id,
                    ticker,
                    metric_key,
                    value,
                    op,
                    thr,
                    ev.get("ingest_id"),
                    execution_path,
                    (ev.get("evidence") or {}).get("url"),
                )
                continue
            action = "NO"
        elif decision_mode == "no_only_on_not_passed":
            if passed:
                logger.info(
                    "SKIP sub_id=%s rule=%s account=%s ev_id=%s ticker=%s metric=%s value=%s op=%s thr=%s ingest_id=%s path=%s reason=no_only_on_not_passed_but_passed url=%s",
                    sub["id"],
                    sub.get("rule_key"),
                    sub.get("account_name"),
                    ev_id,
                    ticker,
                    metric_key,
                    value,
                    op,
                    thr,
                    ev.get("ingest_id"),
                    execution_path,
                    (ev.get("evidence") or {}).get("url"),
                )
                continue
            action = "NO"

        elif decision_mode == "binary_no_yes":
            action = "NO" if passed else "YES"

        else:
            action = "YES" if passed else "NO"

        logger.info(
            "%s sub_id=%s rule=%s account=%s ev_id=%s ticker=%s metric=%s value=%s op=%s thr=%s decision_mode=%s action=%s ingest_id=%s path=%s url=%s",
            "WOULD_TRADE" if not trade_enabled else "TRADE",
            sub["id"],
            sub.get("rule_key"),
            sub.get("account_name"),
            ev_id,
            ticker,
            metric_key,
            value,
            op,
            thr,
            decision_mode,
            action,
            ev.get("ingest_id"),
            execution_path,
            (ev.get("evidence") or {}).get("url"),
        )

        if not trade_enabled:
            continue

        sub_for_trade = dict(sub)
        sub_for_trade["order_price"] = _resolve_order_price_for_action(sub, action)
        logger.info(
            "resolved_order_price sub_id=%s rule=%s action=%s "
            "base_order_price=%r yes_price=%r no_price=%r final_order_price=%r "
            "params=%r",
            sub.get("id"),
            sub.get("rule_key"),
            action,
            sub.get("order_price"),
            (sub.get("params") or {}).get("order_price_yes"),
            (sub.get("params") or {}).get("order_price_no"),
            sub_for_trade.get("order_price"),
            sub.get("params"),
        )

        if use_batch:
            try:
                prepared = build_batch_order_for_decision(sub_for_trade, action)
                if prepared.get("success") and not prepared.get("skipped"):
                    account_name = str(prepared.get("account_name") or "").strip()
                    batch_groups.setdefault(account_name, []).append(
                        {
                            "sub": sub,
                            "prepared": prepared,
                        }
                    )
                else:
                    logger.info(
                        "SKIP batch prepare sub_id=%s ev_id=%s path=%s reason=%s",
                        sub["id"],
                        ev_id,
                        execution_path,
                        prepared.get("reason"),
                    )
            except Exception as e:
                any_failed = True
                failed_notes.append(f"sub_id={sub['id']} batch_prepare_exc={type(e).__name__}:{str(e)[:120]}")
                logger.exception(
                    "batch prepare exception sub_id=%s ev_id=%s ticker=%s metric=%s path=%s",
                    sub["id"], ev_id, ticker, metric_key, execution_path
                )
            continue

        any_trade_attempt = True
        try:
            trade = place_trade_for_decision(sub_for_trade, action)
        except Exception as e:
            any_failed = True
            failed_notes.append(f"sub_id={sub['id']} exc={type(e).__name__}:{str(e)[:120]}")
            logger.exception(
                "order exception sub_id=%s ev_id=%s ticker=%s metric=%s path=%s",
                sub["id"], ev_id, ticker, metric_key, execution_path
            )
            continue

        ok = _finalize_single_trade_result(
            sub=sub,
            trade=trade,
            ev_id=ev_id,
            ticker=ticker,
            execution_path=execution_path,
            failed_notes=failed_notes,
        )
        if ok:
            try:
                _create_manual_trade_confirmation_if_needed(
                    sub=sub,
                    sub_for_trade=sub_for_trade,
                    ev=ev,
                    action=action,
                    value=value,
                    threshold=thr,
                    op=op,
                    execution_path=execution_path,
                    auto_trade=trade,
                )
            except Exception:
                logger.exception(
                    "manual confirmation create failed sub_id=%s ev_id=%s ticker=%s metric=%s path=%s",
                    sub.get("id"),
                    ev_id,
                    ticker,
                    metric_key,
                    execution_path,
                )
        else:
            any_failed = True

    if use_batch:
        batch_failed, batch_attempted = _flush_batch_groups(
            batch_groups=batch_groups,
            ev_id=ev_id,
            ticker=ticker,
            execution_path=execution_path,
            failed_notes=failed_notes,
        )
        any_failed = any_failed or batch_failed
        any_trade_attempt = any_trade_attempt or batch_attempted

    if any_failed:
        _set("ERROR", "; ".join(failed_notes)[:800])
        return "ERROR"

    if any_trade_attempt:
        _set("TRADED", None)
        return "TRADED"

    _set("SKIPPED", "dryrun_or_no_trade_attempt")
    return "SKIPPED"

def _cmp(value: float, threshold: float, op: str) -> bool:
    op = (op or ">=").strip()
    if op in (">", "gt"):
        return value > threshold
    if op in (">=", "ge"):
        return value >= threshold
    if op in ("<", "lt"):
        return value < threshold
    if op in ("<=", "le"):
        return value <= threshold
    if op in ("==", "eq"):
        return value == threshold
    if op in ("!=", "ne"):
        return value != threshold
    # default safe
    return value >= threshold

def _should_use_batch_for_ev(
    *,
    ticker: str,
    metric_key: str,
    execution_path: str,
) -> bool:
    """
    Пока включаем batch только для CBR fast-path.
    Это минимальный и безопасный scope.
    """
    if execution_path != "fast":
        return False
    if ticker != "CBR":
        return False
    if metric_key != "cbr_key_rate_change_bp":
        return False
    return os.getenv("TRADE_BATCH_ENABLED", "1").strip() == "1"


def _finalize_single_trade_result(
    *,
    sub: dict[str, Any],
    trade: dict[str, Any],
    ev_id: int,
    ticker: str,
    execution_path: str,
    failed_notes: list[str],
) -> bool:
    """
    Возвращает True если ордер считается успешно размещённым, иначе False.
    """
    if not isinstance(trade, dict):
        failed_notes.append(f"sub_id={sub['id']} non_dict_trade")
        logger.warning("order bad result sub_id=%s ev_id=%s path=%s", sub["id"], ev_id, execution_path)
        return False

    status = str(trade.get("status") or "").strip().lower()
    raw = trade.get("raw") if isinstance(trade.get("raw"), dict) else {}
    raw_status = str(raw.get("status") or "").strip().lower()
    success_flag = bool(trade.get("success"))
    has_order_id = bool(trade.get("orderID"))

    placed_ok = (
        success_flag
        or has_order_id
        or status in {"placed", "filled", "ok", "submitted", "live"}
        or raw_status in {"placed", "filled", "ok", "submitted", "live"}
    )

    if not placed_ok:
        failed_notes.append(
            f"sub_id={sub['id']} bad_result="
            f"success:{success_flag},status:{status},raw_status:{raw_status},orderID:{trade.get('orderID')}"
        )
        logger.warning(
            "order not placed sub_id=%s ev_id=%s path=%s success=%s status=%s raw_status=%s orderID=%r trade=%r",
            sub["id"],
            ev_id,
            execution_path,
            success_flag,
            status,
            raw_status,
            trade.get("orderID"),
            trade,
        )
        return False

    logger.info(
        "order placed sub_id=%s ev_id=%s path=%s success=%s status=%s raw_status=%s orderID=%r",
        sub["id"],
        ev_id,
        execution_path,
        success_flag,
        status,
        raw_status,
        trade.get("orderID"),
    )

    try:
        msg = build_order_placed_message(
            ticker=ticker,
            trade=trade,
        )
        send_telegram_sync(sub.get("tg_chat_id"), msg)
    except Exception:
        logger.exception(
            "post-trade tg failed sub_id=%s ev_id=%s path=%s",
            sub["id"], ev_id, execution_path
        )

    return True


def _flush_batch_groups(
    *,
    batch_groups: dict[str, list[dict[str, Any]]],
    ev_id: int,
    ticker: str,
    execution_path: str,
    failed_notes: list[str],
) -> tuple[bool, bool]:
    """
    Отправляет батчи по аккаунтам.
    Возвращает (any_failed, any_trade_attempt)
    """
    any_failed = False
    any_trade_attempt = False

    for account_name, items in batch_groups.items():
        if not items:
            continue

        prepared = [x["prepared"] for x in items]
        sub_refs = [x["sub"] for x in items]

        logger.info(
            "batch trade submit account=%s ev_id=%s path=%s batch_size=%s sub_ids=%s",
            account_name,
            ev_id,
            execution_path,
            len(prepared),
            [s.get("id") for s in sub_refs],
        )

        any_trade_attempt = True
        try:
            batch_resp = place_trades_batch_for_account(prepared)
        except Exception as e:
            any_failed = True
            failed_notes.append(f"batch account={account_name} exc={type(e).__name__}:{str(e)[:120]}")
            logger.exception(
                "batch order exception account=%s ev_id=%s path=%s",
                account_name, ev_id, execution_path
            )
            continue

        results = list(batch_resp.get("results") or [])
        if not results:
            any_failed = True
            failed_notes.append(f"batch account={account_name} empty_results")
            logger.warning(
                "batch order empty results account=%s ev_id=%s path=%s raw=%r",
                account_name, ev_id, execution_path, batch_resp,
            )
            continue

        for idx, sub in enumerate(sub_refs):
            trade = results[idx] if idx < len(results) else {
                "success": False,
                "orderID": None,
                "raw": {"error": "missing_result_for_batch_item"},
            }
            ok = _finalize_single_trade_result(
                sub=sub,
                trade=trade,
                ev_id=ev_id,
                ticker=ticker,
                execution_path=execution_path,
                failed_notes=failed_notes,
            )
            if not ok:
                any_failed = True

    return any_failed, any_trade_attempt

# NOTE: run_once() is intentionally "one-iteration only" (no sleeping inside),
# so it can be used by an external orchestrator (extract_and_trade worker).
def run_once(batch: int) -> int:
    _reset_stuck_processing(int(os.getenv("RESET_TRADE_STUCK_MIN", "10")))
    idle_log_sec = float(os.getenv("IDLE_LOG_SEC", "60"))  # 0 = disable idle heartbeat logs
    t0 = time.perf_counter()
    rows = _claim_batch(batch)
    dt = time.perf_counter() - t0
    n = len(rows)

    if n > 0:
        logger.info("claim_batch: n=%s dt=%.3fs", n, dt)
    else:
        if idle_log_sec > 0:
            global _LAST_IDLE_LOG
            now = monotonic()
            if now - _LAST_IDLE_LOG >= idle_log_sec:
                _LAST_IDLE_LOG = now
                logger.info("idle: no rows (dt=%.3fs)", dt)
        return 0

    for ev in rows:
        try:
            process_extracted_value(
                ev,
                execution_path="poll",
                update_trade_status=True,
            )
        except Exception as e:
            logger.exception("process_extracted_value failed ev_id=%s path=poll", ev.get("id"))
            _set_trade_status(int(ev["id"]), "ERROR", str(e)[:800])

    return len(rows)

def main() -> None:
    load_dotenv()
    batch = int(os.getenv("TRADE_BATCH", "50"))
    sleep_s = float(os.getenv("TRADE_SLEEP_SEC", "0.2"))
    logger.info("trade_worker starting batch=%s sleep=%s TRADE_ENABLED=%s", batch, sleep_s, os.getenv("TRADE_ENABLED", "0"))

    while True:
        n = run_once(batch=batch)
        if n == 0:
            time.sleep(sleep_s)


if __name__ == "__main__":
    main()