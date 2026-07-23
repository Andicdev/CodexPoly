from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from common.base import Base
from common import config
import os


_ENGINES = {}
_SESSIONS = {}

_KEEPALIVES = dict(
    # TCP keepalives помогают переживать сетевые "hiccup" и NAT/балансеры,
    # которые могут молча дропать idle SSL-соединения.
    keepalives=1,
    keepalives_idle=int(os.getenv("DB_KEEPALIVES_IDLE", "30")),
    keepalives_interval=int(os.getenv("DB_KEEPALIVES_INTERVAL", "10")),
    keepalives_count=int(os.getenv("DB_KEEPALIVES_COUNT", "5")),
)


_ENGINE_KW = dict(
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=10,
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    # LIFO уменьшает вероятность взять самый "старый" коннект, который уже прибит сервером/сеткой
    pool_use_lifo=True,
    # Явно: при возврате в пул откатываем транзакцию (по умолчанию так и есть, но пусть будет явно)
    pool_reset_on_return="rollback",
    connect_args=_KEEPALIVES,
    # Важное: не выводить значения параметров в логи/исключения
    hide_parameters=True,
    echo=False,
)

def get_engine(role: str = "primary"):
    """Вернёт (и кэширует) Engine для 'primary' или 'analytics'."""
    if role not in _ENGINES:
        url = config.resolve_db_url(role)
        _ENGINES[role] = create_engine(url, **_ENGINE_KW)
    return _ENGINES[role]

def get_session(role: str = "primary"):
    """Вернёт (и кэширует) Session factory для роли."""
    if role not in _SESSIONS:
        _SESSIONS[role] = sessionmaker(bind=get_engine(role), expire_on_commit=False)
    return _SESSIONS[role]

# ── Back-compat: как было раньше ───────────────────────────────────────────────
# Импорт из старого кода продолжит работать с primary:
engine = get_engine("primary")
Session = get_session("primary")
# *если* тебе нужно автосоздание только для primary (как было ранее):
Base.metadata.create_all(engine)
