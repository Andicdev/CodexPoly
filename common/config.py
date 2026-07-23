# common/config.py

import os
from dotenv import load_dotenv
from typing import Set

# Загружаем переменные из .env (только один раз в проекте)
load_dotenv()

# ── PRIMARY (прод) ──────────────────────────────────────────────────────────────
DATABASE_URL_LOCAL = os.getenv("DATABASE_URL_LOCAL")
DATABASE_URL_SERVER_INT = os.getenv("DATABASE_URL_SERVER_INT")
DATABASE_URL_SERVER_EXT = os.getenv("DATABASE_URL_SERVER_EXT")


POLYGONSCAN_API_KEY = os.getenv("POLYGONSCAN_API_KEY")

# ── Polygon RPC providers: Infura / Alchemy / custom ─────────────────────────
# Идея:
#   - ключи Infura и Alchemy храним параллельно;
#   - переключаем провайдера флагами, не затирая ключи;
#   - старые POLYGON_RPC_URL / POLYGON_RPC_URL_TRADES продолжают работать.

# Alchemy
# В .env / Render:
#   ALCHEMY_API_KEY=...
# или полный URL:
#   ALCHEMY_POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/...
ALCHEMY_API_KEY = (os.getenv("ALCHEMY_API_KEY") or "").strip()
ALCHEMY_POLYGON_RPC_URL = (
    (os.getenv("ALCHEMY_POLYGON_RPC_URL") or "").strip()
    or (
        f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
        if ALCHEMY_API_KEY
        else ""
    )
)

# Infura
# В .env / Render:
#   INFURA_PROJECT_ID=...
# или полный URL:
#   INFURA_POLYGON_RPC_URL=https://polygon-mainnet.infura.io/v3/...
INFURA_PROJECT_ID = (
    os.getenv("INFURA_PROJECT_ID")
    or os.getenv("INFURA_API_KEY")
    or os.getenv("INFURA_KEY")
    or ""
).strip()
INFURA_POLYGON_NETWORK = (
    os.getenv("INFURA_POLYGON_NETWORK", "polygon-mainnet") or "polygon-mainnet"
).strip()

INFURA_POLYGON_RPC_URL = (os.getenv("INFURA_POLYGON_RPC_URL") or "").strip()
if not INFURA_POLYGON_RPC_URL and INFURA_PROJECT_ID:
    INFURA_POLYGON_RPC_URL = (
        f"https://{INFURA_POLYGON_NETWORK}.infura.io/v3/{INFURA_PROJECT_ID}"
    )

# Custom/direct URL, если нужен третий провайдер или ручной endpoint.
CUSTOM_POLYGON_RPC_URL = (os.getenv("POLYGON_RPC_URL") or "").strip()

# Флаги выбора провайдера:
#   POLYGON_RPC_PROVIDER=infura|alchemy|custom
#   POLYGON_RPC_PROVIDER_TRADES=infura|alchemy|custom
#   POLYGON_RPC_PROVIDER_BALANCE=infura|alchemy|custom
#
# Если subsystem-флаг не задан, берём POLYGON_RPC_PROVIDER.
# Если вообще никакой provider-флаг не задан, сохраняем старое поведение:
# custom POLYGON_RPC_URL -> Infura -> Alchemy.
POLYGON_RPC_PROVIDER = (os.getenv("POLYGON_RPC_PROVIDER") or "").strip().lower()
POLYGON_RPC_PROVIDER_TRADES = (
    os.getenv("POLYGON_RPC_PROVIDER_TRADES") or ""
).strip().lower()
POLYGON_RPC_PROVIDER_BALANCE = (
    os.getenv("POLYGON_RPC_PROVIDER_BALANCE")
    or os.getenv("POLYGON_RPC_PROVIDER_BALANCES")
    or ""
).strip().lower()


def _polygon_rpc_by_provider(provider: str) -> str:
    p = (provider or "").strip().lower()

    if p in {"infura", "infura.io"}:
        return INFURA_POLYGON_RPC_URL

    if p in {"alchemy", "alchemy.com"}:
        return ALCHEMY_POLYGON_RPC_URL

    if p in {"custom", "direct", "url"}:
        return CUSTOM_POLYGON_RPC_URL

    return ""


def _resolve_polygon_rpc_url(
    *,
    provider: str,
    direct_url: str,
    fallback_url: str,
) -> str:
    """
    provider задан явно -> выбираем named provider.
    provider пустой      -> старое поведение: direct_url -> fallback_url.
    """
    p = (provider or "").strip().lower()

    if p:
        selected = _polygon_rpc_by_provider(p)
        if selected:
            return selected

        # Не валим импорт config.py из-за опечатки во флаге.
        # Просто fallback, чтобы сервис не падал на старте.
        return (direct_url or "").strip() or (fallback_url or "").strip()

    return (direct_url or "").strip() or (fallback_url or "").strip()


# Старый общий fallback: direct URL -> Infura -> Alchemy.
_POLYGON_RPC_LEGACY_DEFAULT = (
    CUSTOM_POLYGON_RPC_URL
    or INFURA_POLYGON_RPC_URL
    or ALCHEMY_POLYGON_RPC_URL
)

# Общий RPC.
POLYGON_RPC_URL = _resolve_polygon_rpc_url(
    provider=POLYGON_RPC_PROVIDER,
    direct_url=CUSTOM_POLYGON_RPC_URL,
    fallback_url=_POLYGON_RPC_LEGACY_DEFAULT,
)

# Trades RPC.
# ВАЖНО: если POLYGON_RPC_PROVIDER_TRADES=alchemy, то он победит старый
# POLYGON_RPC_URL_TRADES, поэтому ключ Infura можно оставить в env.
POLYGON_RPC_URL_TRADES = _resolve_polygon_rpc_url(
    provider=POLYGON_RPC_PROVIDER_TRADES or POLYGON_RPC_PROVIDER,
    direct_url=(os.getenv("POLYGON_RPC_URL_TRADES") or "").strip(),
    fallback_url=POLYGON_RPC_URL,
)

# Balance RPC.
POLYGON_RPC_URL_BALANCE = _resolve_polygon_rpc_url(
    provider=POLYGON_RPC_PROVIDER_BALANCE or POLYGON_RPC_PROVIDER,
    direct_url=(
        (os.getenv("POLYGON_RPC_URL_BALANCE") or "").strip()
        or (os.getenv("POLYGON_RPC_URL_BALANCES") or "").strip()
    ),
    fallback_url=POLYGON_RPC_URL,
)

# Алиас во множественном числе: global_trades_events.py уже пробует
# config.POLYGON_RPC_URL_BALANCES, потом config.POLYGON_RPC_URL_BALANCE.
POLYGON_RPC_URL_BALANCES = POLYGON_RPC_URL_BALANCE

IS_SERVER = os.getenv("SERVER", "false").lower() == "true"

DB_TARGET = os.getenv("DB_TARGET")  # по-прежнему для primary, чтобы не ломать старое
PRIMARY_DB_TARGET = os.getenv("PRIMARY_DB_TARGET", DB_TARGET)
ANALYTICS_DB_TARGET = os.getenv("ANALYTICS_DB_TARGET")  # можно не задавать

def _default_target():
    # Автовыбор для любого пула URL: server_int на сервере, иначе server_ext
    return "server_int" if IS_SERVER else "server_ext"


# Карта URL-ов для двух БД
DATABASES = {
    "primary": {
        "local":      DATABASE_URL_LOCAL,
        "server_int": DATABASE_URL_SERVER_INT,
        "server_ext": DATABASE_URL_SERVER_EXT,
        # прямой URL, если хочешь переопределить сразу:
        "url": os.getenv("DATABASE_URL"),
    },
    "analytics": {
        "local":      os.getenv("ANALYTICS_DATABASE_URL_LOCAL"),
        "server_int": os.getenv("ANALYTICS_DATABASE_URL_SERVER_INT"),
        "server_ext": os.getenv("ANALYTICS_DATABASE_URL_SERVER_EXT"),
        "url":        os.getenv("ANALYTICS_DATABASE_URL"),
    },
}

def resolve_db_url(role: str):
    """
    role: 'primary' | 'analytics'
    Правила: если задан прямой '..._DATABASE_URL' — берём его.
             иначе выбираем по *ROLE*_DB_TARGET (или дефолт по окружению).
    """
    cfg = DATABASES.get(role, {})
    if cfg.get("url"):
        return cfg["url"]
    target = (PRIMARY_DB_TARGET if role == "primary" else ANALYTICS_DB_TARGET) or _default_target()
    url = cfg.get(target)
    if not url:
        raise ValueError(f"❌ URL не задан для role={role}, target={target}")
    return url


# Polymarket API
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY")
POLYMARKET_API_SECRET = os.getenv("POLYMARKET_API_SECRET")
POLYMARKET_API_PASSPHRASE = os.getenv("POLYMARKET_API_PASSPHRASE")
POLYMARKET_ADDRESS1 = os.getenv("POLYMARKET_ADDRESS1")  
PK = os.getenv("PK")

# Trading accounts (encrypt api secrets stored in DB)
# Generate once:
#   python -m scripts.generate_accounts_master_key
# Store in .env / host secrets as ACCOUNTS_MASTER_KEY (DO NOT commit)
ACCOUNTS_MASTER_KEY = os.getenv("ACCOUNTS_MASTER_KEY")

# Telegram
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
User_CHANNEL_ID = os.getenv("USER_CHANNEL_ID")
STRATEGY_CHANNEL_ID = os.getenv("STRATEGY_CHANNEL_ID")

# ── Telegram commands security (for telegram_commands_worker) ─────────────────
def _parse_csv_ints(raw: str | None) -> set[int]:
    if not raw:
        return set()
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except Exception:
            pass
    return out

def _parse_csv_strs(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {p.strip().lstrip("@").lower() for p in raw.split(",") if p.strip()}

TG_COMMANDS_ALLOWED_CHAT_IDS: set[int] = _parse_csv_ints(os.getenv("TG_COMMANDS_ALLOWED_CHAT_IDS", "").strip())
TG_COMMANDS_ADMIN_USER_IDS: set[int] = _parse_csv_ints(os.getenv("TG_COMMANDS_ADMIN_USER_IDS", "").strip())
TG_COMMANDS_ADMIN_USERNAMES: set[str] = _parse_csv_strs(os.getenv("TG_COMMANDS_ADMIN_USERNAMES", "akistenev").strip())

# QuietBuyer channels
# If QUIETBUYER_CHANNEL_ID is not set, strategy may fall back to instance.params["notify_chat"]
# or other strategy defaults.
QUIETBUYER_CHANNEL_ID = os.getenv("QUIETBUYER_CHANNEL_ID")
# Separate channel for JUST_NOTIFY triggers (optional). ms volume default chanel
QUIETBUYER_JUSTNOTIFY_CHANNEL_ID = os.getenv("QUIETBUYER_JUSTNOTIFY_CHANNEL_ID", "-1003654384503") 

# Отдельный канал под уведомления SkyBuyer
# по умолчанию используем твой текущий id -1003367251004
SKYBUYER_CHANNEL_ID = os.getenv("SKYBUYER_CHANNEL_ID", "-1003367251004")
MARKET_ALERTS_CHANNEL_ID = os.getenv("MARKET_ALERTS_CHANNEL_ID")
BINANCE_PRICE_ALERTS_CHANNEL_ID = os.getenv("BINANCE_PRICE_ALERTS_CHANNEL_ID")
EVENT_ALERTS_CHANNEL_ID = os.getenv("EVENT_ALERTS_CHANNEL_ID", "-1002881599821")
# Отдельный канал для ошибок воркеров/агентов
# по умолчанию используем твой канал "My errors"
ERRORS_CHANNEL_ID = os.getenv("ERRORS_CHANNEL_ID", "-1003429125459")

# ── Microstrategy keyword alerts ─────────────────────────────────────────────
MICROSTRATEGY_ALERTS_ENABLED = os.getenv("MICROSTRATEGY_ALERTS_ENABLED", "true").lower() == "true"
MICROSTRATEGY_ALERTS_PERIOD_SEC = int(os.getenv("MICROSTRATEGY_ALERTS_PERIOD_SEC", "300"))
MICROSTRATEGY_ALERTS_KEYWORD = os.getenv("MICROSTRATEGY_ALERTS_KEYWORD", "microstrategy")
# Если не задан — таск будет fallback'иться в MARKET_ALERTS_CHANNEL_ID / CHANNEL_ID / STRATEGY_CHANNEL_ID
MICROSTRATEGY_ALERTS_CHANNEL_ID = os.getenv("MICROSTRATEGY_ALERTS_CHANNEL_ID", "-1003322427842")
MICROSTRATEGY_ALERTS_LOOKBACK_HOURS = int(os.getenv("MICROSTRATEGY_ALERTS_LOOKBACK_HOURS", "48"))
MICROSTRATEGY_ALERTS_LIMIT = int(os.getenv("MICROSTRATEGY_ALERTS_LIMIT", "50"))

# Агентские параметры (пример)
ORDERS_INTERVAL = int(os.getenv("ORDERS_INTERVAL", 60))

# Другие параметры, по мере необходимости
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

POLYMARKET_DATA_API_URL_TRADES = os.getenv("POLYMARKET_DATA_API_URL_TRADES")
POLYMARKET_DATA_API_URL_POSITIONS = os.getenv("POLYMARKET_DATA_API_URL_POSITIONS")

# activity monitor defaults (можно переопределять через .env)
MERGE_START_WINDOW_H = int(os.getenv("MERGE_START_WINDOW_H", "72"))
ACTIVITY_PERIOD_MIN  = int(os.getenv("ACTIVITY_PERIOD_MIN", "10"))
ACTIVITY_LOOKBACK_MIN = int(os.getenv("ACTIVITY_LOOKBACK_MIN", "90"))
ENABLE_WATCHLIST_SCAN = os.getenv("ENABLE_WATCHLIST_SCAN", "false").lower() == "true"
WATCHLIST_USD_THRESHOLD = float(os.getenv("WATCHLIST_USD_THRESHOLD", "10000"))
# если не задано отдельно:
POLYMARKET_DATA_API_URL_ACTIVITY = os.getenv("POLYMARKET_DATA_API_URL_ACTIVITY", "https://data-api.polymarket.com/activity")

# public users task
PUBLIC_USERS_ENABLED = os.getenv("PUBLIC_USERS_ENABLED", "true").lower() == "true"
PUBLIC_USERS_PERIOD_MIN = int(os.getenv("PUBLIC_USERS_PERIOD_MIN", "30"))
PUBLIC_USERS_BATCH = int(os.getenv("PUBLIC_USERS_BATCH", "50"))
PUBLIC_USERS_SLEEP_BETWEEN = float(os.getenv("PUBLIC_USERS_SLEEP_BETWEEN", "1.0"))

# trades ingest tail (REST /trades → trades_ingested)
# можно не задавать — возьмутся дефолты из кода таска
# HTTP/2 для httpx-клиента (по умолчанию выключен, чтобы не требовать пакет h2)
POLYMARKET_HTTP2 = os.getenv("POLYMARKET_HTTP2", "false").lower() == "true"
TRADES_TAIL_LIMIT = int(os.getenv("TRADES_TAIL_LIMIT", "10000"))
TRADES_TAIL_PERIOD_SEC = float(os.getenv("TRADES_TAIL_PERIOD_SEC", "2.0"))
TRADES_TAIL_ADAPT_MIN_SEC = float(os.getenv("TRADES_TAIL_ADAPT_MIN_SEC", "0.5"))
TRADES_TAIL_ADAPT_MAX_SEC = float(os.getenv("TRADES_TAIL_ADAPT_MAX_SEC", "10.0"))

# Почасовая сводка загрузки (в телеграм)
INGEST_SUMMARY_ENABLED = os.getenv("INGEST_SUMMARY_ENABLED", "true").lower() == "true"
INGEST_SUMMARY_PERIOD_MIN = int(os.getenv("INGEST_SUMMARY_PERIOD_MIN", "60"))
TELEGRAM_INGEST_CHAT_ID = os.getenv("TELEGRAM_INGEST_CHAT_ID")  # опционально

# cleanup
INGEST_CLEAN_ENABLED = os.getenv("INGEST_CLEAN_ENABLED", "true").lower() == "true"
INGEST_CLEAN_PERIOD_MIN = int(os.getenv("INGEST_CLEAN_PERIOD_MIN", "5"))
INGEST_CLEAN_KEEP_HOURS = int(os.getenv("INGEST_CLEAN_KEEP_HOURS", "2"))
INGEST_CLEAN_BATCH = int(os.getenv("INGEST_CLEAN_BATCH", "8000"))
INGEST_CLEAN_STATS_DAYS = int(os.getenv("INGEST_CLEAN_STATS_DAYS", "14"))

# cleanup архива trades_ingested_archive ------------------------------
TRADES_ARCHIVE_CLEAN_ENABLED = os.getenv("TRADES_ARCHIVE_CLEAN_ENABLED", "true").lower() == "true"
TRADES_ARCHIVE_CLEAN_PERIOD_MIN = int(os.getenv("TRADES_ARCHIVE_CLEAN_PERIOD_MIN", "60"))
TRADES_ARCHIVE_KEEP_DAYS = int(os.getenv("TRADES_ARCHIVE_KEEP_DAYS", "3"))
TRADES_ARCHIVE_CLEAN_BATCH = int(os.getenv("TRADES_ARCHIVE_CLEAN_BATCH", "200000"))
TRADES_ARCHIVE_CLEAN_SQL_CHUNK = int(os.getenv("TRADES_ARCHIVE_CLEAN_SQL_CHUNK", "2000"))

# Сколько дней храним события из order_filled_events_subgraph.
# 0 или отрицательное значение — не чистим (храним всё).
GLOBAL_TRADES_KEEP_DAYS = int(os.getenv("GLOBAL_TRADES_KEEP_DAYS", "1"))

# Размер страницы при выборке global trades (RPC и др.).
# Совместимость: если раньше использовался MP_PAGE_SIZE — он будет учтён как fallback.
GLOBAL_TRADES_PAGE_SIZE = int(os.getenv("GLOBAL_TRADES_PAGE_SIZE", os.getenv("MP_PAGE_SIZE", "1000")))


# ── Global Data-API limiter / retry settings ───────────────────────────────────
API_TOTAL_PER_10S = int(os.getenv("API_TOTAL_PER_10S", "180"))
API_TRADES_PER_10S = int(os.getenv("API_TRADES_PER_10S", "60"))
API_TARGET_UTIL = float(os.getenv("API_TARGET_UTIL", "0.65"))  # консервативнее по умолчанию

API_MAX_RETRY_AFTER_SEC = float(os.getenv("API_MAX_RETRY_AFTER_SEC", "15.0"))
API_MIN_SLEEP_ON_429 = float(os.getenv("API_MIN_SLEEP_ON_429", "0.25"))

# ── Optional static proxy for Data API only (проксируем только data-api.*) ────
# пример: http://user:pass@proxy.host:port
DATA_API_PROXY_URL = os.getenv("DATA_API_PROXY_URL", "")

# ── Wallets enrich task ────────────────────────────────────────────────────────
WALLETS_ENRICH_ENABLED = os.getenv("WALLETS_ENRICH_ENABLED", "true").lower() == "true"
WALLETS_ENRICH_BATCH = int(os.getenv("WALLETS_ENRICH_BATCH", "80"))
WALLETS_ENRICH_PERIOD_SEC = int(os.getenv("WALLETS_ENRICH_PERIOD_SEC", "30"))
WALLETS_ENRICH_PAGE_LIMIT = int(os.getenv("WALLETS_ENRICH_PAGE_LIMIT", "200"))
WALLETS_ENRICH_MAX_PAGES = int(os.getenv("WALLETS_ENRICH_MAX_PAGES", "20"))
WALLETS_ENRICH_HTTP_TIMEOUT = float(os.getenv("WALLETS_ENRICH_HTTP_TIMEOUT", "25.0"))
WALLETS_ENRICH_FAST = os.getenv("WALLETS_ENRICH_FAST", "true").lower() == "true"
WALLETS_ENRICH_JITTER_SEC = float(os.getenv("WALLETS_ENRICH_JITTER_SEC", "2"))
WALLETS_ENRICH_FAST_ONLY = os.getenv("WALLETS_ENRICH_FAST_ONLY", "true").lower() == "true"
WALLETS_ENRICH_PAGE_JITTER_SEC = float(os.getenv("WALLETS_ENRICH_PAGE_JITTER_SEC", "1"))
WALLETS_ENRICH_ABORT_BACKOFF_SEC = int(os.getenv("WALLETS_ENRICH_ABORT_BACKOFF_SEC", "90"))
# множитель паузы между кошельками (просил x2)
WALLETS_ENRICH_JITTER_MULT = float(os.getenv("WALLETS_ENRICH_JITTER_MULT", "1.5"))
# ── РЕЖИМ ОДНОГО ПРОХОДА ───────────────────────────────────────────────────────
# Если true: после успешного (depth=1) обогащения кошелька больше не трогаем его.
WALLETS_ENRICH_ONESHOT = os.getenv("WALLETS_ENRICH_ONESHOT", "true").lower() == "true"
# Какой статус писать в all_wallets.enrich_status после one-shot
WALLETS_ENRICH_DONE_STATUS = os.getenv("WALLETS_ENRICH_DONE_STATUS", "done_once")
# На сколько дней уводить next_enrich_after, чтобы не подхватывать повторно
WALLETS_ENRICH_DONE_TTL_DAYS = int(os.getenv("WALLETS_ENRICH_DONE_TTL_DAYS", "3650"))  # по умолчанию ~10 лет

# Небольшая задержка перед запуском wallets_enrich (сек), чтобы не стартовать в пике
WALLETS_ENRICH_START_DELAY_SEC = float(os.getenv("WALLETS_ENRICH_START_DELAY_SEC", "5"))
# ── ДОП. ПАУЗЫ ВОКРУГ POSITIONS ───────────────────────────────────────────────
# Пауза перед первым вызовом /positions для каждого кошелька (сек)
WALLETS_ENRICH_SLEEP_BEFORE_POS_SEC = float(os.getenv("WALLETS_ENRICH_SLEEP_BEFORE_POS_SEC", "0.6"))
# Пауза между /positions и /closed-positions (сек)

WALLETS_ENRICH_SLEEP_BETWEEN_POS_CALLS_SEC = float(os.getenv("WALLETS_ENRICH_SLEEP_BETWEEN_POS_CALLS_SEC", "0.6"))

# Вариант обогащения: "v1" = лёгкий (без /positions), "full" = старый
WALLETS_ENRICH_VARIANT = os.getenv("WALLETS_ENRICH_VARIANT", "v1")

# --- Rate-limit / 429 backoff tuning ---
# Сколько секунд откладывать ЗАДАЧУ, если она словила ThrottleAbort (429).
# Для wallets_enrich переопределяется WALLETS_ENRICH_ABORT_BACKOFF_SEC.
TASK_ABORT_BACKOFF_SEC = int(os.getenv("TASK_ABORT_BACKOFF_SEC", "60"))



# Опциональная короткая «глобальная передышка» монитора при любом 429 (секунды).
# 0 — отключено. Поставь, например, 5–15, если хочешь на время «остудить» остальной пул задач.
MONITOR_ABORT_PAUSE_SEC = float(os.getenv("MONITOR_ABORT_PAUSE_SEC", "0"))

# ── Gamma Markets API (НЕ Data API) ────────────────────────────────────────────
# База для /events и /markets
POLYMARKET_GAMMA_API_BASE = os.getenv("POLYMARKET_GAMMA_API_BASE", "https://gamma-api.polymarket.com")

# HTTP-клиент
GAMMA_HTTP_TIMEOUT       = float(os.getenv("GAMMA_HTTP_TIMEOUT", "20.0"))
GAMMA_HTTP2              = os.getenv("GAMMA_HTTP2", "false").lower() == "true"

# Пагинация и «растяжка» фулл-скана
GAMMA_EVENTS_PAGE_LIMIT  = int(os.getenv("GAMMA_EVENTS_PAGE_LIMIT", "300"))
# 0 => без лимита (идём до конца)
GAMMA_MAX_PAGES_PER_RUN  = int(os.getenv("GAMMA_MAX_PAGES_PER_RUN", "0"))   # ограничение на один прогон

# Параметры таска
GAMMA_INGEST_PERIOD_SEC  = int(os.getenv("GAMMA_INGEST_PERIOD_SEC", "15"))
GAMMA_JITTER_SEC         = float(os.getenv("GAMMA_JITTER_SEC", "0.05"))
GAMMA_RPS_TARGET         = float(os.getenv("GAMMA_RPS_TARGET", "6.0"))      # целевой RPS (6–8 безопасно)
GAMMA_ABORT_BACKOFF_SEC  = int(os.getenv("GAMMA_ABORT_BACKOFF_SEC", "90"))   # откладываем после 429

# Параметры воркера (если гоняем отдельно от монитора)
GAMMA_WORKER_PERIOD_SEC        = int(os.getenv("GAMMA_WORKER_PERIOD_SEC", "5"))
GAMMA_GLOBAL_ABORT_PAUSE_SEC   = float(os.getenv("GAMMA_GLOBAL_ABORT_PAUSE_SEC", "0"))

# Как часто делать ПОЛНЫЙ рескан /events (секунды). По факту – частота тяжёлого прогона.
# Это главный рычаг снижения CPU. Рекомендуем 300–900.
GAMMA_EVENTS_RESYNC_SEC        = int(os.getenv("GAMMA_EVENTS_RESYNC_SEC", "250"))

# Сон между страницами /events (в секундах). Маленькая пауза заметно снижает пилообразную загрузку CPU.
GAMMA_PAGE_SLEEP_BETWEEN_SEC   = float(os.getenv("GAMMA_PAGE_SLEEP_BETWEEN_SEC", "0.05"))


# Лог новых рынков (вставленных за текущий прогон)
GAMMA_LOG_NEW_MARKETS = os.getenv("GAMMA_LOG_NEW_MARKETS", "true").lower() == "true"
GAMMA_LOG_NEW_MARKETS_LIMIT = int(os.getenv("GAMMA_LOG_NEW_MARKETS_LIMIT", "20"))


# Явный алиас БД, чтобы таск и воркер однозначно брали «primary»
PRIMARY_DB_ALIAS = os.getenv("PRIMARY_DB_ALIAS", "primary")

# Уведомления в Telegram при появлении новых рынков
GAMMA_NEW_MARKETS_NOTIFY = os.getenv("GAMMA_NEW_MARKETS_NOTIFY", "true").lower() == "true"
# Куда слать (если не указать, попробуем MARKET_ALERTS_CHANNEL_ID, потом CHANNEL_ID)
GAMMA_NEW_MARKETS_CHAT_ID = os.getenv("GAMMA_NEW_MARKETS_CHAT_ID")

# ── Очистка «давно не виденных» рынков ───────────────────────────────────────
# включить/выключить чистку
GAMMA_CLEAN_INACTIVE_MARKETS_ENABLED = os.getenv("GAMMA_CLEAN_INACTIVE_MARKETS_ENABLED", "true").lower() == "true"
# порог неактивности (в часах)
GAMMA_CLEAN_INACTIVE_MARKETS_HOURS = int(os.getenv("GAMMA_CLEAN_INACTIVE_MARKETS_HOURS", "24"))
# максимум удалений за один прогон (0 = без лимита)
GAMMA_CLEAN_MAX_ROWS = int(os.getenv("GAMMA_CLEAN_MAX_ROWS", "5000"))
# подстраховка: удалять только если рынок уже закрыт/резолвнут
GAMMA_CLEAN_ONLY_CLOSED = os.getenv("GAMMA_CLEAN_ONLY_CLOSED", "true").lower() == "true"
# верхняя планка удаления за один прогон (несколько батчей подряд)
GAMMA_CLEAN_MAX_PER_RUN = int(os.getenv("GAMMA_CLEAN_MAX_PER_RUN", "20000"))

# «чистящий» шаг воркера отдельно от основного цикла
GAMMA_CLEAN_TASK_ENABLED = os.getenv("GAMMA_CLEAN_TASK_ENABLED", "true").lower() == "true"
GAMMA_CLEAN_TASK_PERIOD_SEC = int(os.getenv("GAMMA_CLEAN_TASK_PERIOD_SEC", "300"))

# ── Бэкфилл тегов рынков (/markets?include_tag=true&id=...) ──────────────────
# включить/выключить бэкфилл после прохода по /events
GAMMA_MARKET_TAG_BACKFILL_ENABLED = os.getenv("GAMMA_MARKET_TAG_BACKFILL_ENABLED", "true").lower() == "true"
# сколько market_id за один батч запроса
GAMMA_MARKET_TAG_BATCH_SIZE = int(os.getenv("GAMMA_MARKET_TAG_BATCH_SIZE", "100"))
# максимум батчей за прогон (0 = без лимита)
GAMMA_MARKET_TAG_MAX_BATCHES = int(os.getenv("GAMMA_MARKET_TAG_MAX_BATCHES", "10"))
# пауза между батчами
GAMMA_MARKET_TAG_SLEEP_BETWEEN_SEC = float(os.getenv("GAMMA_MARKET_TAG_SLEEP_BETWEEN_SEC", "0.25"))

# писать ли в БД рынки, которые сейчас не активны (активность определяем из полей active/closed/resolved/archived)
GAMMA_STORE_INACTIVE_MARKETS = os.getenv("GAMMA_STORE_INACTIVE_MARKETS", "false").lower() == "true"

# Период бэкфилла тегов рынков (сек) – отдельно от основного цикла
GAMMA_TAGS_BACKFILL_PERIOD_SEC = int(os.getenv("GAMMA_TAGS_BACKFILL_PERIOD_SEC", "300"))

# ── Чистка событий без активных рынков ───────────────────────────────────────
# включить/выключить чистку эвентов
GAMMA_EVENT_CLEAN_ENABLED = os.getenv("GAMMA_EVENT_CLEAN_ENABLED", "true").lower() == "true"
# удалять только закрытые эвенты (false = удалять любые без активных рынков)
GAMMA_EVENT_CLEAN_ONLY_CLOSED = os.getenv("GAMMA_EVENT_CLEAN_ONLY_CLOSED", "false").lower() == "true"
# максимальное число удалений за прогон (0 = без лимита)
GAMMA_EVENT_CLEAN_MAX_PER_RUN = int(os.getenv("GAMMA_EVENT_CLEAN_MAX_PER_RUN", "10000"))
# размер батча выборки id на удаление
GAMMA_EVENT_CLEAN_BATCH = int(os.getenv("GAMMA_EVENT_CLEAN_BATCH", "2000"))

# ── Исключение рынков по тегам (например, спорт) ─────────────────────────────
# Список через запятую; допускаются id/slug/label (сравнение регистронезависимое)
GAMMA_EXCLUDE_TAG_IDS = os.getenv("GAMMA_EXCLUDE_TAG_IDS", "").strip()


# ── Targeted refresh for monitored_event ─────────────────────────────────────
# Нужен для старых/глубоких event, до которых общий /events ingest может не дойти
# при небольшом GAMMA_MAX_PAGES_PER_RUN.
MONITORED_EVENT_REFRESH_ENABLED = os.getenv("MONITORED_EVENT_REFRESH_ENABLED", "true").lower() == "true"
MONITORED_EVENT_REFRESH_PERIOD_SEC = int(os.getenv("MONITORED_EVENT_REFRESH_PERIOD_SEC", "180"))
# 0 => без лимита. Практически можно держать 80-120, если monitored_event немного.
MONITORED_EVENT_REFRESH_MAX_PAGES = int(os.getenv("MONITORED_EVENT_REFRESH_MAX_PAGES", "80"))
MONITORED_EVENT_REFRESH_LOG_LIMIT = int(os.getenv("MONITORED_EVENT_REFRESH_LOG_LIMIT", "20"))

# ── Interesting markets (выборка рынков под стратегии) ────────────────────────
# Включить/выключить таск переноса из gamma_market → interesting_markets
INTERESTING_MARKETS_TASK_ENABLED = os.getenv("INTERESTING_MARKETS_TASK_ENABLED", "true").lower() == "true"

# Как часто гонять таск (сек)
INTERESTING_MARKETS_PERIOD_SEC = int(os.getenv("INTERESTING_MARKETS_PERIOD_SEC", "300"))

# Сколько максимум рынков за один прогон переносим в interesting_markets
INTERESTING_MARKETS_MAX_PER_RUN = int(os.getenv("INTERESTING_MARKETS_MAX_PER_RUN", "200"))

# Окно по added_at (в часах): смотрим только рынки, впервые добавленные
# в gamma_market за последние N часов. Если 1 — берём примерно «за последний час».
INTERESTING_MARKETS_ADDED_HOURS = int(os.getenv("INTERESTING_MARKETS_ADDED_HOURS", "1"))

# Теги, по которым ИСКЛЮЧАЕМ рынки (slug/id/label через запятую, регистр не важен),
# например: "crypto,5-minute,15-minute"
INTERESTING_MARKETS_EXCLUDE_TAG_IDS = os.getenv("INTERESTING_MARKETS_EXCLUDE_TAG_IDS",
             "sports,up-or-down").strip()

#INTERESTING_MARKETS_EXCLUDE_TAG_IDS = os.getenv("INTERESTING_MARKETS_EXCLUDE_TAG_IDS", "").strip()

#INTERESTING_MARKETS_EXCLUDE_TAG_IDS = os.getenv("INTERESTING_MARKETS_EXCLUDE_TAG_IDS", "").strip()

# Минимальный спред рынка для попадания в interesting_markets
INTERESTING_MARKETS_MIN_SPREAD = float(
     os.getenv("INTERESTING_MARKETS_MIN_SPREAD", "0.1")
)

# TTL интересных рынков (часы) для фоновой чистки
INTERESTING_MARKETS_TTL_HOURS = int(
     os.getenv("INTERESTING_MARKETS_TTL_HOURS", "12")
)

# Отдельный таск для чистки таблицы interesting_markets
INTERESTING_MARKETS_CLEANUP_ENABLED = os.getenv(
     "INTERESTING_MARKETS_CLEANUP_ENABLED", "true"
).lower() == "true"
INTERESTING_MARKETS_CLEANUP_PERIOD_SEC = int(
    os.getenv("INTERESTING_MARKETS_CLEANUP_PERIOD_SEC", "600")
)

# Если true — игнорируем флаг approved в interesting_markets и запускаем скайбайер
# по всем активным рынкам из таблицы
INTERESTING_MARKETS_IGNORE_APPROVED = os.getenv(
    "INTERESTING_MARKETS_IGNORE_APPROVED", "true"
).lower() == "true"

# Максимальное число одновременно активных инстансов skybuyer
# 0 = без ограничения (поведение как сейчас)
SKYBUYER_MAX_ACTIVE_INSTANCES = int(
    os.getenv("SKYBUYER_MAX_ACTIVE_INSTANCES", "1")
)

# ── SkyBuyer / strategy aliases ──────────────────────────────────────────────

def _split_env_set(name: str, default: str) -> set[str]:
    raw = os.getenv(name, default)
    return {p.strip().upper() for p in raw.split(",") if p.strip()}

# Какие значения outcome считаем за YES / NO в gamma_outcome
# Можно переопределить в .env, например:
#   SKYBUYER_YES_OUTCOMES="YES,Y,WIN"
#   SKYBUYER_NO_OUTCOMES="NO,N,LOSE"
SKYBUYER_YES_OUTCOMES: set[str] = _split_env_set(
    "SKYBUYER_YES_OUTCOMES", "YES,UP"
)
SKYBUYER_NO_OUTCOMES: set[str] = _split_env_set(
    "SKYBUYER_NO_OUTCOMES", "NO,DOWN"
)

# ── Market structure / wallet enrich tuning ─────────────────────────────────
# батчинг/паузы для wallet_enrich_data
MM_WALLET_ENRICH_SLEEP_BETWEEN_WALLETS = float(
    os.getenv("MM_WALLET_ENRICH_SLEEP_BETWEEN_WALLETS", "0.30")
)
MM_WALLET_ENRICH_WALLET_BATCH = int(
    os.getenv("MM_WALLET_ENRICH_WALLET_BATCH", "25")
)
MM_WALLET_ENRICH_SLEEP_BETWEEN_BATCHES = float(
    os.getenv("MM_WALLET_ENRICH_SLEEP_BETWEEN_BATCHES", "1.5")
)

# wallet-subgraph retry/backoff controls (Goldsky)
GOLDSKY_WALLET_MAX_RETRIES = int(os.getenv("GOLDSKY_WALLET_MAX_RETRIES", "8"))
GOLDSKY_WALLET_BACKOFF_BASE = float(os.getenv("GOLDSKY_WALLET_BACKOFF_BASE", "1.0"))
GOLDSKY_WALLET_BACKOFF_MAX = float(os.getenv("GOLDSKY_WALLET_BACKOFF_MAX", "30"))
GOLDSKY_WALLET_COOLDOWN_ON_503 = float(os.getenv("GOLDSKY_WALLET_COOLDOWN_ON_503", "60"))
GOLDSKY_WALLET_COOLDOWN_ON_429 = float(os.getenv("GOLDSKY_WALLET_COOLDOWN_ON_429", "20"))