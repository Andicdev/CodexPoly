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

Keep non-secret configuration on the service itself. Keep confidential values
in a restricted Northflank Secret Group named `cbr-trading-secrets`.

Safe fixed service values:

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
# Ordinary GTC: immediately take asks up to the limit, then rest any remainder.
CBR_LIVE_POST_ONLY=0
CBR_LIVE_ALLOWED_ACCOUNT=kinderSman
```

Northflank is outside Render's private network, so use
`CBR_ON_RENDER=0` and the external Render database URL.

Create `cbr-trading-secrets` as a **Secret values** group, restrict inheritance
to the `cbr-rate-trader` service, and enter these values manually:

```dotenv
DATABASE_URL_SERVER_EXT=
ACCOUNTS_MASTER_KEY=
TG_BOT_TOKEN=
TELEGRAM_INGEST_CHAT_ID=
```

Do not inspect, snapshot, screenshot, copy, or export Secret Group,
service-Environment, protected-content, or password pages through an automated
browser session. This applies even before values are revealed because password
manager autofill can populate the page DOM. Automation may navigate to the
page and must then hand control to a human. Once the group is inherited by the
service, remove duplicate confidential keys from the service-level environment
because direct service variables override inherited values.

The safe migration order while the service is paused is:

1. Create the restricted `cbr-trading-secrets` group.
2. Enter and save the four values manually.
3. Attach or inherit the group only for `cbr-rate-trader`.
4. Remove the same four keys from the direct service environment.
5. Restart in dry-run mode and check presence without exposing values:

   ```text
   python -m cbr_trading.secret_guard
   ```

The command reports key names as present or missing and never prints values,
lengths, hashes, or connection details. The account encryption key requires a
data migration before rotation; never replace it independently.

For daily automation, use a Northflank role or API token that can deploy and
read logs but cannot reveal Secret Group values. Grant secret editing only
during an explicit human-supervised rotation.

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

At this point the account is authenticated, balances and market metadata are
checked, all possible GTC orders are pre-signed, and every possible order has
a committed `PENDING` idempotency reservation. After publication the runner
does not refresh the order book, sign orders, or access the database before it
sends one batch request per account. Result persistence and Telegram happen
after the batch request.

Before arming the production worker for an event, run a small real order from
the same Northflank runtime with
`python -m cbr_trading.live --full-path-live-test ...`. This must use an
explicit rule, action, quantity, price, confirmation flag, and stable
`--test-run-id`. Reusing that id is blocked by the same persistent
idempotency mechanism before any second order can be sent.

After the event, inspect the order results and Telegram message. The hosted
worker then logs that it is idle instead of restarting the completed event.

## Earnings shadow source service

Deploy earnings ingestion as a separate combined service. Do not add it to the
CBR trading service and do not attach trading-account or Polymarket signing
secrets.

- repository and build settings: the same as above;
- instances: exactly 1;
- networking: no public ports;
- command: `python -u -m cbr_trading.earnings`;
- migration behavior: readiness check only; it never applies migration 004;
- execution mode: permanently `shadow` for this checkpoint.

Safe service variables:

```dotenv
PYTHONUNBUFFERED=1
LOG_LEVEL=INFO
CBR_ON_RENDER=0
EARNINGS_WORKER_MODE=shadow
EARNINGS_FETCH_TIMEOUT_SEC=15
EARNINGS_MAX_DOCUMENT_BYTES=8388608
EARNINGS_FETCH_ATTEMPTS=3
EARNINGS_FETCH_RETRY_SEC=0.5
EARNINGS_RECONNECT_INITIAL_SEC=1
EARNINGS_RECONNECT_MAX_SEC=30
EARNINGS_NO_RULES_RETRY_SEC=30
EARNINGS_HEARTBEAT_SEC=60
```

Set `EARNINGS_HTTP_USER_AGENT` to an operator-approved SEC identification
string. For every accepted exhibit, the worker races the public SEC URL
against the SEC-API Download API and parses the first validated response.
The identification string is sent only on the direct SEC route and is not
logged. The SEC-API credential is sent to `archive.sec-api.io` in the
`Authorization` header; it is never placed in the document URL.

Create a restricted Secret Group for this service and enter manually:

```dotenv
DATABASE_URL_SERVER_EXT=
SEC_API_KEY=
```

If the existing SEC service uses `SEC_API_IO_KEY` or `SEC_API_STREAM_KEY`,
that key name is also supported. Never copy its value through logs, shell
arguments, screenshots, browser snapshots, or chat.

A healthy startup contains:

```text
Earnings shadow worker schema ready mode=shadow
SEC earnings shadow stream connecting watches=1
```

Before starting the service, run
`python -m scripts.check_earnings_shadow_runtime` in its runtime. The output
must show `mode=shadow`, one active NVTS scope, one watch, no missing parser,
and only a boolean SEC credential presence flag.

The periodic heartbeat reports only connection state and aggregate counts.
An accepted document logs its scope, parser status, database row identifiers,
and public EPS value. It never logs the WebSocket URI, API credential, raw
document, database URL, or authenticated values.

## Earnings resolution orchestrator service

Deploy the consumer/executor as a third private combined service. Do not put
`SEC_API_KEY` on this service, and do not attach trading secrets to the
earnings shadow source service.

- instances: exactly 1;
- networking: no public ports;
- command: `python -u -m cbr_trading.resolution_hosted`;
- schema behavior: readiness checks only; it never applies migrations 005
  or 006;
- initial mode: `shadow`.

Safe initial values:

```dotenv
PYTHONUNBUFFERED=1
LOG_LEVEL=INFO
CBR_ON_RENDER=0
RESOLUTION_ORCHESTRATOR_MODE=shadow
RESOLUTION_ORCHESTRATOR_POLL_SEC=0.25
RESOLUTION_ORCHESTRATOR_HEARTBEAT_SEC=30
RESOLUTION_ORCHESTRATOR_NO_PROFILES_SEC=30
RESOLUTION_SUPERVISION_ENABLED=0
```

The orchestrator needs the primary database URL. `shadow` mode needs no
trading key. `preflight` and `live` additionally use the existing restricted
trading secret group containing `ACCOUNTS_MASTER_KEY`, and the ordinary
`CBR_LIVE_*` safety settings. Never attach the SEC credential.

The promotion sequence is:

1. apply migrations 005 and 006 explicitly while the new service is stopped;
2. configure NVTS, WWD, and BBBY profiles; they remain `DISABLED`;
3. switch the service to `preflight`, attach the trading secret group, and
   enable one in-window profile at a time;
4. verify that two templates per profile are ready;
5. return profiles to disabled while changing any parameters;
6. only after explicit approval set `RESOLUTION_ORCHESTRATOR_MODE=live`,
   `RESOLUTION_SUPERVISION_ENABLED=1`, and the existing live safety guards;
7. restart once before the preparation window and do not hot-edit an enabled
   profile.

Healthy startup for three profiles contains only safe aggregate identifiers:

```text
Hosted resolution ready mode=preflight profiles=3 templates=6
```

The service loads only enabled profiles whose mandatory preparation/expiry
window contains the current time. It rejects a profile whose condition ID
does not exactly match its source rule. In `live`, the existing resolution
claim ledger prevents a restarted service from claiming the same
scope/template twice, and the persistent order supervisor monitors both
explicit tick events and real finer-price levels in the order book.
