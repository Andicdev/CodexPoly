from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from common.db import get_session
from common.logger import get_logger
from models.t_central_bank_policy_history import CentralBankPolicyHistory

logger = get_logger(__name__)
PrimarySession = get_session("primary")


def _as_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        if isinstance(v, Decimal):
            return float(v)
        return float(v)
    except Exception:
        return None


def infer_change_bps(
    *,
    target_value: float | None,
    prev_target_value: float | None,
    direction: str | None,
) -> float | None:
    """
    Generic rule:
      - if both current and previous target exist: compute delta in bps
      - else if direction == hold: return 0.0
      - else: unknown
    """
    target = _to_float(target_value)
    prev = _to_float(prev_target_value)
    dir_norm = str(direction or "").strip().lower() or None

    if target is not None and prev is not None:
        return round((target - prev) * 100.0, 6)

    if dir_norm == "hold":
        return 0.0

    return None


def get_previous_policy_decision(
    *,
    bank_code: str,
    instrument_code: str,
    decision_time_utc: datetime,
) -> dict[str, Any] | None:
    with PrimarySession() as s:
        stmt = (
            select(CentralBankPolicyHistory)
            .where(
                CentralBankPolicyHistory.bank_code == bank_code,
                CentralBankPolicyHistory.instrument_code == instrument_code,
                CentralBankPolicyHistory.decision_time_utc < _as_utc(decision_time_utc),
            )
            .order_by(CentralBankPolicyHistory.decision_time_utc.desc())
            .limit(1)
        )
        row = s.execute(stmt).scalar_one_or_none()
        if row is None:
            return None

        return {
            "id": int(row.id),
            "decision_time_utc": row.decision_time_utc,
            "target_value": _to_float(row.target_value),
            "prev_target_value": _to_float(row.prev_target_value),
            "change_bps": _to_float(row.change_bps),
            "direction": row.direction,
            "source": row.source,
            "source_doc_type": row.source_doc_type,
            "source_url": row.source_url,
            "ingest_id": row.ingest_id,
        }


def upsert_policy_decision(
    *,
    bank_code: str,
    instrument_code: str,
    decision_time_utc: datetime | None,
    effective_time_utc: datetime | None = None,
    target_value: float | None = None,
    direction: str | None = None,
    source: str | None = None,
    source_doc_type: str | None = None,
    source_url: str | None = None,
    ingest_id: int | None = None,
    extracted_value_id: int | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision_dt = _as_utc(decision_time_utc)
    effective_dt = _as_utc(effective_time_utc) if effective_time_utc else None

    prev = get_previous_policy_decision(
        bank_code=bank_code,
        instrument_code=instrument_code,
        decision_time_utc=decision_dt,
    )
    prev_target_value = prev.get("target_value") if prev else None
    change_bps = infer_change_bps(
        target_value=target_value,
        prev_target_value=prev_target_value,
        direction=direction,
    )

    payload = {
        "bank_code": bank_code,
        "instrument_code": instrument_code,
        "decision_time_utc": decision_dt,
        "effective_time_utc": effective_dt,
        "target_value": target_value,
        "prev_target_value": prev_target_value,
        "change_bps": change_bps,
        "direction": direction,
        "source": source,
        "source_doc_type": source_doc_type,
        "source_url": source_url,
        "ingest_id": ingest_id,
        "extracted_value_id": extracted_value_id,
        "evidence": evidence or {},
        "updated_at": datetime.now(timezone.utc),
    }

    with PrimarySession() as s:
        stmt = insert(CentralBankPolicyHistory).values(**payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                CentralBankPolicyHistory.bank_code,
                CentralBankPolicyHistory.instrument_code,
                CentralBankPolicyHistory.decision_time_utc,
            ],
            set_={
                "effective_time_utc": stmt.excluded.effective_time_utc,
                "target_value": stmt.excluded.target_value,
                "prev_target_value": stmt.excluded.prev_target_value,
                "change_bps": stmt.excluded.change_bps,
                "direction": stmt.excluded.direction,
                "source": stmt.excluded.source,
                "source_doc_type": stmt.excluded.source_doc_type,
                "source_url": stmt.excluded.source_url,
                "ingest_id": stmt.excluded.ingest_id,
                "extracted_value_id": stmt.excluded.extracted_value_id,
                "evidence": stmt.excluded.evidence,
                "updated_at": datetime.now(timezone.utc),
            },
        ).returning(CentralBankPolicyHistory.id)
        row_id = s.execute(stmt).scalar_one()
        s.commit()

    out = {
        "id": int(row_id),
        "bank_code": bank_code,
        "instrument_code": instrument_code,
        "decision_time_utc": decision_dt,
        "effective_time_utc": effective_dt,
        "target_value": target_value,
        "prev_target_value": prev_target_value,
        "change_bps": change_bps,
        "direction": direction,
        "source": source,
        "source_doc_type": source_doc_type,
        "source_url": source_url,
        "ingest_id": ingest_id,
        "extracted_value_id": extracted_value_id,
    }

    logger.info(
        "cb_policy_upsert bank=%s instrument=%s decision_time=%s target=%s prev=%s change_bps=%s direction=%s ingest_id=%s id=%s",
        bank_code,
        instrument_code,
        decision_dt.isoformat(),
        target_value,
        prev_target_value,
        change_bps,
        direction,
        ingest_id,
        row_id,
    )
    return out