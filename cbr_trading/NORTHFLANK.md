# Northflank deployment

Use a continuously running **combined service**, not a cron job. The service
needs to be running and fully warmed before the CBR publication time.

## Service

Create a combined service in the target Northflank project:

- repository: this repository;
- branch: `main`;
- build type: Dockerfile;
- Dockerfile: `/Dockerfile`;
- build context: repository root;
- instances: exactly 1;
- networking: no public ports;
- command: use the Dockerfile default;
- CI/CD: disable automatic deployment after the final verified build so a
  code push cannot restart the worker near the release.

The container starts `python -u -m cbr_trading.hosted_worker`. After the CBR
event is processed it remains alive in an idle state, preventing the platform
from restarting the completed event.

## Runtime variables

Safe fixed values:

```dotenv
PYTHONUNBUFFERED=1
LOG_LEVEL=INFO
BOR_MODE=hot
BOR_RELEASE_DATE=24.07.2026
BOR_RELEASE_TIME_SUFFIX=133000key_e
BOR_POLL_SLEEP_SEC=0.25
BOR_HEARTBEAT_SEC=10
BOR_CONNECT_TIMEOUT_SEC=0.5
BOR_READ_TIMEOUT_SEC=0.5
BOR_PREFIX_MAX_BYTES=32768
BOR_PREFIX_CHUNK_SIZE=2048
BOR_DISABLE_CACHE_BUSTER=0
BOR_PREV_RATE=14.25
CBR_ON_RENDER=0
CBR_RULES_DB_ENABLED=1
CBR_TELEGRAM_ENABLED=1
CBR_LIVE_POST_ONLY=1
CBR_LIVE_ALLOWED_ACCOUNT=kinderSman
```

Northflank is outside Render's private network, so use
`CBR_ON_RENDER=0` and the external Render database URL.

Add these values securely in Northflank. Do not commit their contents:

```dotenv
DATABASE_URL_SERVER_EXT=
ACCOUNTS_MASTER_KEY=
TG_BOT_TOKEN=
TELEGRAM_INGEST_CHAT_ID=
```

Controlled trading values must be set only after the final three-rule
preflight:

```dotenv
CBR_DRY_RUN=1
CBR_LIVE_TRADING_ENABLED=0
CBR_LIVE_MAX_ORDER_QTY=
CBR_LIVE_MAX_NOTIONAL=
CBR_LIVE_MAX_TOTAL_NOTIONAL=
```

Use `CBR_DRY_RUN=1` and `CBR_LIVE_TRADING_ENABLED=0` for the first deployment.
After the final rule preview and explicit approval, update the caps, set
`CBR_DRY_RUN=0` and `CBR_LIVE_TRADING_ENABLED=1`, then restart once.

## Logs

Open the service's **Observe → Logs** view and enable live tailing. A healthy
waiting worker writes a heartbeat every 10 seconds:

```text
CBR waiting iteration=... status=200 reason=not_published_yet ...
```

A blocked request is explicit:

```text
CBR fetch failed iteration=... status=403 error=...
```

Before leaving the service armed, the log must also contain:

```text
CBR live executor warmed before polling rules=... accounts=... outcomes=...
```

After the event, inspect the order results and Telegram message. The hosted
worker then logs that it is idle instead of restarting the completed event.
