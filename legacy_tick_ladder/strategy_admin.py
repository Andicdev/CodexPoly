# FILE: logic/strategy_admin.py
from __future__ import annotations

import uuid
import re
from typing import Optional, Iterable, Any
from datetime import datetime, timezone as _tz
from enum import Enum as _Enum
from sqlalchemy.orm import Session

from models.t_strategy import Strategy as StrategyModel, StrategyStatus

from models.t_rule import Rule as RuleModel
from models.t_strategy_instance import StrategyInstance, StrategyInstanceStatus
from models.t_strategy_instance_rule import StrategyInstanceRule
from models.t_strategy_event import StrategyEvent
from models.t_rule_fire_log import RuleFireLog

# 👇 если хочешь по аналогии с rules_admin класть маркет в listen_asset — можно подтянуть add_listen_asset
from logic.listen_admin import add_listen_asset
from logic.rules_admin import (
    add_price_order_rule,
    add_price_alert_rule,
    add_wait_for_entry_rule,
)  # для типовых правил и WAIT_FOR_ENTRY

def _ensure_instance_listen_asset(
    s: Session,
    *,
    inst: StrategyInstance,
    rule: RuleModel | None = None,
    note_prefix: str = "auto by instance",
) -> None:
    """
    Системная подписка asset -> listen_asset.

    Приоритет:
    1) rule.asset_id
    2) inst.params.asset_id
    3) inst.params.asset
    """
    asset_id = None
    condition_id = None
    market_slug = None

    if rule is not None:
        asset_id = getattr(rule, "asset_id", None) or None
        condition_id = getattr(rule, "condition_id", None) or None
        market_slug = getattr(rule, "market_slug", None) or None

    if not asset_id:
        params = dict(getattr(inst, "params", None) or {})
        asset_id = (
            params.get("asset_id")
            or params.get("assetId")
            or params.get("asset")
            or None
        )
        condition_id = condition_id or getattr(inst, "condition_id", None) or None
        market_slug = market_slug or getattr(inst, "question", None) or None

    if asset_id:
        add_listen_asset(
            s,
            str(asset_id),
            note=f"{note_prefix} {inst.id}",
            enabled=True,
            condition_id=condition_id,
            market_slug=market_slug,
        )

def _slugify_instance_name(s: str) -> str:
    """
    Делает безопасное имя инстанса:
      - lower
      - только a-z0-9_
      - обрезка до 64
    """
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:64]

def _default_instance_name(*, strategy_name: str | None, condition_id: str, instance_id: str) -> str:
    st = _slugify_instance_name(strategy_name or "inst") or "inst"
    cid8 = (condition_id or "").strip().lower().replace("0x", "")[:8] or "cid"
    iid6 = (instance_id or "").strip().lower().replace("-", "")[:6] or "iid"
    return _slugify_instance_name(f"{st}_{cid8}_{iid6}") or f"inst_{iid6}"


# === NEW: экземпляры стратегии ===
def create_strategy_instance(
    s: Session,
    *,
    strategy_id: str,
    condition_id: str,
    question: str | None = None,
    params: dict | None = None,
    strategy_name: str | None = None,
    name: str | None = None,
    runtime_state: dict | None = None,
    status: StrategyInstanceStatus = StrategyInstanceStatus.PENDING,
) -> str:
    """
    Создаёт инстанс стратегии.

    Если params не переданы, подтягивает их из Strategy.params.
    Если strategy_name не передано, подтягивает Strategy.name.
    При отсутствии runtime_state инициализирует его фазой ожидания входа.
    """
    st_obj: StrategyModel | None = None

    if params is None or strategy_name is None:
        st_obj = (
            s.query(StrategyModel)
             .filter(StrategyModel.id == strategy_id)
             .one_or_none()
        )

    # base params: либо явно переданные, либо взятые из стратегии
    if params is None:
        params = dict(st_obj.params or {}) if st_obj and st_obj.params else {}

    # имя стратегии в инстанс
    if strategy_name is None:
        strategy_name = st_obj.name if st_obj else None

    # runtime_state по умолчанию — ждём вход
    if runtime_state is None:
        runtime_state = {
            "phase": "WAIT_FOR_ENTRY",
            "wait_started_at": datetime.now(_tz.utc).isoformat(),
            "last_check_ts": None,
        }

    # ВАЖНО: strategy_instance.name = NOT NULL + UNIQUE → должен быть установлен ДО flush()
    inst_id = str(uuid.uuid4())
    inst_name = _slugify_instance_name(name or "")
    if not inst_name:
        inst_name = _default_instance_name(strategy_name=strategy_name, condition_id=condition_id, instance_id=inst_id)

    inst = StrategyInstance(
        id=inst_id,
        name=inst_name,
        strategy_id=strategy_id,
        strategy_name=strategy_name,
        question=question,
        condition_id=condition_id,
        params=params,
        runtime_state=runtime_state,
        status=status,
    )
    s.add(inst)
    s.flush()
    _notify_strategies_changed(s)
    _enqueue_strategy_wake_event(s, instance_id=str(inst.id), note="instance_created")
    return inst.id



def start_strategy_instance(
    s: Session,
    *,
    instance_id: str,
    create_rule_kind: str | None = None,   # "PRICE_ORDER"/"PRICE_ALERT"/None
    create_rule_kwargs: dict | None = None,
    step_order: int = 0,
    role: str | None = "ENTER",
    ensure_listen_asset: bool = True,
) -> dict:
    """Переводит инстанс в RUNNING и создаёт/привязывает первичные правила согласно params/аргументам."""
    # Важно: id у нас TEXT → фильтруем как строку
    inst = s.query(StrategyInstance).filter(StrategyInstance.id == str(instance_id)).first()

    if not inst:
        raise ValueError("strategy_instance not found")
    inst.status = StrategyInstanceStatus.RUNNING
    s.add(inst); s.flush()

    rid = None
    if create_rule_kind:
        kw = dict(create_rule_kwargs or {})
        kw.setdefault("condition_id", inst.condition_id)
        if create_rule_kind == "PRICE_ORDER":
            rid = add_price_order_rule(s, **kw)
        elif create_rule_kind == "PRICE_ALERT":
            rid = add_price_alert_rule(s, **kw)
        elif create_rule_kind == "WAIT_FOR_ENTRY":
            # техническое правило ожидания входа (SkyBuyer и подобные)
            rid = add_wait_for_entry_rule(s, **kw)
        else:
            raise ValueError(f"Unsupported create_rule_kind={create_rule_kind}")
    if rid:
        # привязываем РУЛ к ИНСТАНСУ и обеспечиваем подписку
        s.merge(StrategyInstanceRule(strategy_instance_id=inst.id, rule_id=rid, step_order=step_order, role=role))
        rule = s.query(RuleModel).get(rid)
        if ensure_listen_asset:
            _ensure_instance_listen_asset(
                s,
                inst=inst,
                rule=rule,
                note_prefix="auto by instance",
            )
    elif ensure_listen_asset:
        _ensure_instance_listen_asset(
            s,
            inst=inst,
            rule=None,
            note_prefix="auto by instance",
        )
    s.commit()
    _notify_strategies_changed(s)
    return {"instance_id": inst.id, "status": inst.status.name, "rule_id": rid}


def attach_rule_to_instance(
    s: Session,
    *,
    instance_id: str,
    rule_id: str,
    step_order: int = 0,
    role: str | None = None,
    ensure_listen_asset: bool = True,
):

    inst = s.query(StrategyInstance).filter(StrategyInstance.id == str(instance_id)).first()
    if not inst:
        raise ValueError("strategy_instance not found")
    s.merge(StrategyInstanceRule(strategy_instance_id=instance_id, rule_id=rule_id, step_order=step_order, role=role))
    rule = s.query(RuleModel).get(rule_id)
    if ensure_listen_asset:
        _ensure_instance_listen_asset(
            s,
            inst=inst,
            rule=rule,
            note_prefix="attach by instance",
        )
    s.commit()
    _notify_strategies_changed(s)
    return {"instance_id": instance_id, "rule_id": rule_id}


def launch_strategy_for_market_instance(
    s: Session,
    *,
    strategy_name: str,
    condition_id: str,
    question: str | None = None,
    create_rule_kind: str | None = "PRICE_ORDER",
    create_rule_kwargs: dict | None = None,
    name: str | None = None,
) -> dict:
    """Высокоуровневый запуск: найти стратегию по имени → создать (или найти) инстанс по (strategy_id, condition_id)
    → стартовать его → вернуть статус. Если уже существует — вернуть его статус и связанные правила."""
    st = s.query(StrategyModel).filter(StrategyModel.name == strategy_name).first()
    if not st:
        raise ValueError(f"Strategy '{strategy_name}' not found")
    # ВАЖНО: strategy_instance.strategy_id у нас TEXT → приводим UUID к строке
    st_id = str(st.id)
    # уникальность по (strategy_id, condition_id)
    inst = (
        s.query(StrategyInstance)
         .filter(StrategyInstance.strategy_id == st_id,
                 StrategyInstance.condition_id == condition_id)
         .first()
    )
    if not inst:
        inst_id = create_strategy_instance(
            s,
            strategy_id=st_id,               # ← строковый id
            condition_id=condition_id,
            question=question,
            params=dict(st.params or {}),    # протаскиваем params стратегии
            strategy_name=st.name,           # и имя стратегии в инстанс
            status=StrategyInstanceStatus.PENDING,
            name=name,
        )
        return start_strategy_instance(
            s,
            instance_id=str(inst_id),
            create_rule_kind=create_rule_kind,
            create_rule_kwargs=create_rule_kwargs or {}
        )
    else:
        # собрать связанные правила
        links = (s.query(StrategyInstanceRule).filter(StrategyInstanceRule.strategy_instance_id == inst.id).all())
        return {"already_exists": True, "instance_id": inst.id, "status": inst.status.name, "rules": [ln.rule_id for ln in links]}

def _notify_strategies_changed(s: Session):
    try:
        s.execute("NOTIFY strategies_changed;")
    except Exception:
        # если нет прав/триггера — молчим
        pass

def _enqueue_strategy_wake_event(s: Session, *, instance_id: str, note: str = "WAKE"):
    """Кладём служебное событие в strategy_event, чтобы marketchanel подхватил новый инстанс без рестарта.

    Требование: в БД должен быть триггер, который делает NOTIFY strategy_event_new на INSERT.
    """
    try:
        iid = str(instance_id)
        ev = StrategyEvent(
            instance_id=iid,
            event_type="WAKE",
            # чтобы не пересекаться с реальными order_id и уникальностью (event_type, order_id)
            order_id=f"WAKE:{iid}",
            payload={"type": "WAKE", "note": note, "instance_id": iid},
        )
        s.add(ev)
        s.flush()
    except Exception:
        # может быть unique violation или отсутствует таблица — не критично
        try:
            s.rollback()
        except Exception:
            pass

def create_strategy(
    s: Session,
    *,
    name: str,
    kind: str,
    params: dict | None = None,
    enabled: bool = True,
    tg_chat_id: str | None = None,
) -> str:
    """Создаёт запись в strategy и возвращает id (UUID строкой)."""
    sid = str(uuid.uuid4())
    m = StrategyModel(
        id=sid,
        name=name,
        kind=kind,
        status=StrategyStatus.ENABLED if enabled else StrategyStatus.DISABLED,
        params=(params or {}),
        tg_chat_id=tg_chat_id,
    )
    s.add(m)
    s.commit()
    _notify_strategies_changed(s)
    return sid

def set_strategy_status(s: Session, *, strategy_id: str, enabled: bool):
    st = StrategyStatus.ENABLED if enabled else StrategyStatus.DISABLED
    s.query(StrategyModel).filter(StrategyModel.id == strategy_id).update({"status": st})
    s.commit()
    _notify_strategies_changed(s)

def strategy_to_dict(obj: StrategyModel) -> dict[str, Any]:
    """
    Преобразует ORM-объект Strategy в json-дружелюбный словарь.
    Берём все колонки таблицы:
      - Enum → .value
      - datetime → ISO-строка
      - остальные значения как есть.
    """
    data: dict[str, Any] = {}
    for col in StrategyModel.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, _Enum):
            val = val.value
        elif isinstance(val, datetime):
            val = val.isoformat()
        data[col.name] = val
    return data

def strategy_instance_to_dict(obj: StrategyInstance) -> dict[str, Any]:
    """
    Преобразует ORM-объект StrategyInstance в json-дружелюбный словарь.
    Все колонки таблицы:
      - Enum → .value
      - datetime → ISO-строка
      - остальные значения как есть.
    """
    data: dict[str, Any] = {}
    for col in StrategyInstance.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, _Enum):
            val = val.value
        elif isinstance(val, datetime):
            val = val.isoformat()
        data[col.name] = val
    return data

def get_strategy_instance(s: Session, instance_id: str) -> Optional[dict[str, Any]]:
    """
    Возвращает инстанс стратегии по id как dict со всеми полями таблицы.
    Если не найден — вернёт None.
    """
    obj = (
        s.query(StrategyInstance)
        .filter(StrategyInstance.id == str(instance_id))
        .one_or_none()
    )
    if obj is None:
        return None
    return strategy_instance_to_dict(obj)


def get_strategy_by_name(s: Session, name: str) -> Optional[dict[str, Any]]:
    """
    Возвращает стратегию по имени как dict со всеми полями таблицы.
    Если стратегия не найдена — возвращает None.
    """
    obj = (
        s.query(StrategyModel)
        .filter(StrategyModel.name == name)
        .one_or_none()
    )
    if obj is None:
        return None
    return strategy_to_dict(obj)


def update_strategy(
    s: Session,
    *,
    strategy_id: str | None = None,
    name: str | None = None,
    new_name: str | None = None,
    kind: str | None = None,
    enabled: Optional[bool] = None,
    tg_chat_id: Optional[str] = None,
    params: Optional[dict] = None,
    merge_params: bool = True,
) -> str:
    """
    Обновляет стратегию по id или name.

    - strategy_id / name — идентификатор (достаточно одного).
    - new_name           — переименовать стратегию.
    - kind               — поменять тип стратегии.
    - enabled            — включить/выключить (меняет status).
    - tg_chat_id         — канал уведомлений по умолчанию.
    - params             — новые параметры:
        • merge_params=True  → поверх существующих
        • merge_params=False → полностью заменить.
    """
    if not strategy_id and not name:
        raise ValueError("update_strategy: требуется указать strategy_id или name")

    q = s.query(StrategyModel)
    if strategy_id:
        q = q.filter(StrategyModel.id == strategy_id)
    else:
        q = q.filter(StrategyModel.name == name)

    obj = q.one_or_none()
    if obj is None:
        key = f"id={strategy_id!r}" if strategy_id else f"name={name!r}"
        raise ValueError(f"update_strategy: стратегия не найдена по {key}")

    if new_name is not None and new_name != obj.name:
        obj.name = new_name

    if kind is not None and kind != obj.kind:
        obj.kind = kind

    if enabled is not None:
        new_status = StrategyStatus.ENABLED if enabled else StrategyStatus.DISABLED
        if obj.status != new_status:
            obj.status = new_status

    if tg_chat_id is not None and tg_chat_id != obj.tg_chat_id:
        obj.tg_chat_id = tg_chat_id

    if params is not None:
        if merge_params:
            merged = dict(obj.params or {})
            merged.update(params)
            obj.params = merged
        else:
            obj.params = params

    s.commit()
    _notify_strategies_changed(s)
    return obj.id

def get_strategy_extended_info(s: Session, strategy_name: str) -> dict[str, Any]:
    """
    Расширенная информация по стратегии:

      - сама стратегия (как dict)
      - список инстансов:
        • id, status, condition_id, strategy_name
        • runtime_state
        • timer_state
        • привязанные правила:
            - rule_id, rule_name, rule_type, status, step_order, role
            - три последних id из rule_fire_log
    """
    # 1) находим стратегию
    st: StrategyModel | None = (
        s.query(StrategyModel)
         .filter(StrategyModel.name == strategy_name)
         .one_or_none()
    )
    if st is None:
        return {
            "strategy": None,
            "instances": [],
        }

    st_id = str(st.id)

    # 2) все инстансы этой стратегии
    instances = (
        s.query(StrategyInstance)
         .filter(StrategyInstance.strategy_id == st_id)
         .order_by(StrategyInstance.created_at.asc())
         .all()
    )

    result_instances: list[dict[str, Any]] = []

    for inst in instances:
        # привязанные rules через таблицу связей
        links = (
            s.query(StrategyInstanceRule)
             .filter(StrategyInstanceRule.strategy_instance_id == inst.id)
             .order_by(StrategyInstanceRule.step_order.asc(), StrategyInstanceRule.rule_id.asc())
             .all()
        )

        rules_info: list[dict[str, Any]] = []

        for ln in links:
            rule: RuleModel | None = (
                s.query(RuleModel)
                 .filter(RuleModel.id == ln.rule_id)
                 .one_or_none()
            )

            # три последних срабатывания по этому rule
            last_logs = (
                s.query(RuleFireLog)
                 .filter(RuleFireLog.rule_id == ln.rule_id)
                 .order_by(RuleFireLog.id.desc())
                 .limit(3)
                 .all()
            )

            rules_info.append(
                {
                    "rule_id": ln.rule_id,
                    "rule_name": getattr(rule, "name", None) if rule else None,
                    "rule_type": rule.type.value if rule and hasattr(rule, "type") else None,
                    "rule_status": rule.status.value if rule and hasattr(rule, "status") else None,
                    "step_order": getattr(ln, "step_order", None),
                    "role": getattr(ln, "role", None),
                    "last_fire_log_ids": [log.id for log in last_logs],
                }
            )

        result_instances.append(
            {
                "instance_id": inst.id,
                "status": inst.status.value if hasattr(inst.status, "value") else str(inst.status),
                "condition_id": inst.condition_id,
                "strategy_name": getattr(inst, "strategy_name", None),
                "question": getattr(inst, "question", None),
                "params": inst.params,
                "runtime_state": inst.runtime_state,
                "timer_state": inst.timer_state,
                "rules": rules_info,
            }
        )

    return {
        "strategy": strategy_to_dict(st),
        "instances": result_instances,
    }
