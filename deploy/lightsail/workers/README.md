# CodexPoly SEC and resolution workers on Lightsail

## Service boundary

The base worker stack contains four private services built from the same
reviewed CodexPoly image:

- `earnings-worker` retains its compatibility service name and runs
  `python -u -m cbr_trading.earnings`; internally it owns one shared SEC
  filing connection for earnings and MSTR shadow routers plus a conditional
  Strategy Ledger poller;
- `resolution-worker` runs
  `python -u -m cbr_trading.resolution_hosted`;
- `notification-worker` runs
  `python -u -m cbr_trading.notifications` and is the only new hosted
  service that receives Telegram credentials;
- `profile-scheduler-worker` runs
  `python -u -m cbr_trading.profile_lifecycle`, owns only database access,
  and moves reviewed schedules through their time-based states.

The production trading overlay adds `profile-readiness-worker`. It receives
the same narrowly mounted account secrets as the resolution service and runs
authenticated preparation for both outcomes without calling `execute()` or
submitting an order. The scheduler itself never receives trading secrets.

Neither service publishes a host port. Both join the existing internal
PostgreSQL network and connect to `postgres:5432` as `codexpoly_app`. The
database network remains `internal`; each worker also joins a dedicated bridge
network used only for outbound traffic. No service publishes a port on either
network. Both use the AWS link-local resolver `169.254.169.253`; this avoids
forwarding external lookups from rootless Docker to the host-only
systemd-resolved stub.
`earnings-worker` receives the SEC credential but never receives a trading
credential. The base `resolution-worker` starts in `shadow` and receives only
the application database password. Confirmed events are written
idempotently to `source_notification_outbox`; Telegram HTTP delivery and
retries happen later in `notification-worker`, outside the ingestion and
trading hot paths.

Profile schedules are separate from execution configuration. `MANUAL` is
inert, `AUTO_PREFLIGHT` can request and record a readiness check but cannot
enable a profile, and `AUTO_LIVE` is additionally gated by the global
`PROFILE_SCHEDULER_AUTO_LIVE_ENABLED` switch, a fresh readiness result, the
active time window, and an aggregate notional cap. Every transition is
append-only audited and enqueued to the same Telegram outbox. The `ACTIVE`
message says that the profile status is `ENABLED`; it does not claim that an
order was submitted.

`MSTR_BTC_SHADOW_ENABLED=true` enables only the checked-in, time-bounded MSTR
source watch. The worker verifies the append-only holdings schema, pins the
validated pre-window baseline, persists the append-only source audit, and logs
aggregate parser/signal output. It does not create an MSTR resolution profile,
execution claim, order intent, or order.

`MSTR_BTC_LEDGER_ENABLED=true` adds the official Strategy Ledger as a second
MSTR transport. The worker checks enabled in-window
`mstr_btc_resolution` profiles every two seconds and makes no external Ledger
request while that set is empty. While at least one profile is active,
production polls every two seconds using ETag validation. A new snapshot must
retain baseline row `116` at `843775` BTC, add only contiguous rows, and
reconcile every signed change against running holdings before it can persist
a fact. The SEC WebSocket remains connected independently of profile status.

`EARNINGS_PUBLIC_SOURCES_ENABLED=true` adds the company IR and press-wire RSS
feeds configured in each earnings rule. The worker checks enabled in-window
`earnings_resolution` scopes and makes no external IR or wire request while
that set is empty. Each transport persists its own source event and validated
fact; all of them resolve through the same event-scoped earnings signal.
Different feeds are polled concurrently so a slow IR host cannot delay its
wire peer. A failing feed receives its own bounded exponential retry backoff
while healthy feeds retain the configured polling interval. Production uses
a half-second cadence only while at least one reviewed earnings profile is
enabled and in-window. The RSS parser
accepts known HTML character entities emitted by common IR platforms while
continuing to reject DTD and entity declarations. Responses with a valid
`Content-Length` are read to that exact bound instead of waiting for a broken
CDN connection close. The NVTS company feed uses the official
`navitassemi.gcs-web.com` endpoint rather than the unstable vanity-host alias.

`EARNINGS_SEC_CURRENT_POLL_ENABLED=true` adds the official
`data.sec.gov/submissions/CIK##########.json` API as a low-latency fallback to
the always-connected SEC-API WebSocket. It is gated by the same enabled,
in-window earnings scopes and makes no SEC HTTP request while that set is
empty. Requests use conditional validators and a shared five-request-per-
second pacer, leaving headroom below the SEC ten-request-per-second
fair-access ceiling. A new initial `8-K` must contain Item 2.02, fall inside
the bounded release lookback, and expose exactly one `EX-99.1` on the official
filing-detail page before it enters the existing SEC router and parser.

The resolution worker also owns the checked-in July 2026 FOMC decision
source. It makes no Federal Reserve request unless at least one in-window
`fed_fomc` profile is enabled. While active, it races the Board statement,
Board implementation note, New York Fed PDF mirror, and the Board monetary
policy RSS feed; the first document that yields one unambiguous target range
wins. One canonical rate-change signal is then fanned out to the five
Polymarket buckets through separate scopes and the common prepared executor.
The Telegram summary is enqueued only after all five trading coordinators
have been evaluated and includes the winning official source URL.

| Environment | Compose source | Installed path |
| --- | --- | --- |
| staging | `compose.staging.yml` | `/opt/codexpoly/staging/apps/workers/compose.yml` |
| production | `compose.production.yml` | `/opt/codexpoly/production/apps/workers/compose.yml` |
| production trading overlay | `compose.production.trading.yml` | `/opt/codexpoly/production/apps/workers/compose.trading.yml` |

The production overlay is the only file that mounts
`ACCOUNTS_MASTER_KEY` and
`TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED`. Do not use it for the initial shadow
deployment.

Secret presence is checked against `resolution-worker` for the base stack and
`resolution-worker-trading` before applying the production overlay.

## Non-secret deployment configuration

Compose requires `CODEXPOLY_IMAGE_REF` to identify the reviewed image. Use an
immutable digest for production. `EARNINGS_HTTP_USER_AGENT` must contain the
operator-approved SEC identity. It is used only by the direct SEC side of the
parallel document fetch; the SEC-API archive side authenticates through a
header. Aggregate route latency and the winner are logged without URLs,
documents, or credentials. These values are deployment configuration, not
secret values.

The trading overlay additionally requires:

```text
CBR_LIVE_MAX_ORDER_QTY
CBR_LIVE_MAX_NOTIONAL
CBR_LIVE_MAX_TOTAL_NOTIONAL
```

The public account metadata table binds `abccbaq` to its proxy wallet, venue
`polymarket_clob`, signature type `2`, and active status. The overlay reads
that metadata from PostgreSQL and combines it with the encrypted private-key
file-secret. No private key, master key, database password, or API token is
stored in the metadata table or deployment configuration.

The overlay defaults to:

```text
RESOLUTION_ORCHESTRATOR_MODE=preflight
RESOLUTION_SUPERVISION_ENABLED=0
CBR_LIVE_TRADING_ENABLED=0
```

Live mode therefore requires explicit values for all three guards, including
`RESOLUTION_SUPERVISION_ENABLED=1` and
`CBR_LIVE_TRADING_ENABLED=1`.

The base scheduler independently defaults to:

```text
PROFILE_SCHEDULER_AUTO_LIVE_ENABLED=0
```

The checked-in July batch uses only `AUTO_PREFLIGHT`. Successful preparation
therefore leaves every `resolution_execution_profiles.status` value
`DISABLED`.

## Account secret installation

The production account has no legacy `trading_accounts` row. Its public
metadata is stored in `trading_account_metadata`. An infrastructure
administrator installs a fresh encryption key and encrypted private key
together:

```bash
sudo --preserve-env=CODEXPOLY_IMAGE_REF \
  /opt/codexpoly/config/install-trading-account.sh production
```

`CODEXPOLY_IMAGE_REF` must be an immutable `sha256` image reference. The
installer starts that reviewed image with no network, a read-only root
filesystem, no Linux capabilities, and only the production secret directory
mounted. A human enters the Polymarket private key twice through the hidden
terminal prompt. The container generates and writes:

```text
/opt/codexpoly/secrets/prod/ACCOUNTS_MASTER_KEY
/opt/codexpoly/secrets/prod/TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED
```

The values are never displayed. Existing files make the operation fail closed;
the installer cannot rotate or replace them. The ordinary
`install-secret.sh` also refuses to install either member of this pair
individually.

Staging must not receive these files. It remains in shadow mode without the
production account.

## Promotion sequence

1. Start PostgreSQL and apply committed migrations.
2. Start the staging base stack and run the synthetic earnings path.
3. Start the production base stack in shadow mode.
4. Verify both workers' aggregate heartbeats without inspecting secrets.
5. Install the production account secrets through the human-only installer.
6. Verify the `resolution-worker-trading` secret set by name only.
7. Apply migration 012 and the reviewed schedule seed before starting the
   scheduler.
8. Start the base scheduler with automatic live activation disabled.
9. Start only `profile-readiness-worker` from the production trading overlay
   for scheduled authenticated preflight.
10. Verify `READY`/`BLOCKED` lifecycle events and Telegram delivery while all
    execution profiles remain `DISABLED`.
11. Enable live mode and `AUTO_LIVE` only after a separate explicit approval
    and after the Northflank live resolution worker is stopped.

Only one live resolution worker may exist across Northflank and Lightsail. The
two databases do not share execution claims, so simultaneous live workers are
not protected from one another by idempotency.

Earnings automation is operated as separate `PRE_MARKET` and `POST_MARKET`
live blocks. The blocks share the universal worker but never share an
implicit activation: the non-selected session stays `MANUAL` and its profiles
stay `DISABLED`. Required metadata, completion semantics, and production
checks are documented in `deploy/lightsail/LIVE_MARKET_BLOCKS.md`.

For the first authenticated NVTS preflight, use the guarded SQL files in
`deploy/lightsail/preflight` in numeric order. The first file refuses to run
when any profile is already enabled, the second verifies exactly one
in-window profile in a read-only transaction, and the third restores the
checked-in NVTS window and returns every profile to `DISABLED`.

The three MSTR markets use aggregate cap `1000`, with quantity and per-order
caps still fixed at `50`. Apply
`005_enable_all_aggregate_1000.sql`, run the one-shot module below through
the production trading overlay, then apply the common restore and
disabled-profile invariant:

```text
python -u -m cbr_trading.simulations.production_mstr_btc_preflight \
  --confirm PRODUCTION_MSTR_AUTHENTICATED_PREFLIGHT \
  --all-profiles
```

hosted preflight/live batch guard counts the worst selected outcome from
every enabled profile. The three-profile maximum is `149.85`, within the
reviewed cap of `1000`. The runner requires the enabled set to match the
requested checked-in profiles and reports `order_submitted=false`,
`source_fact_polled=false`, and `executor_execute_called=false`.

The staging synthetic path is explicitly non-submitting and does not need a
trading-account secret:

```bash
docker run --rm \
  --network codexpoly-staging-backend \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --mount type=bind,src=/home/codexdeploy/.config/codexpoly/secrets/staging/DATABASE_APP_PASSWORD,dst=/run/secrets/DATABASE_APP_PASSWORD,readonly \
  --env CODEXPOLY_ENVIRONMENT=staging \
  --env PRIMARY_DB_TARGET=server_int \
  --env DATABASE_HOST=postgres \
  --env DATABASE_PORT=5432 \
  --env DATABASE_NAME=codexpoly \
  --env DATABASE_USER=codexpoly_app \
  --env DATABASE_APP_PASSWORD_FILE=/run/secrets/DATABASE_APP_PASSWORD \
  --env RESOLUTION_ORCHESTRATOR_MODE=shadow \
  --env RESOLUTION_SUPERVISION_ENABLED=0 \
  --env CBR_LIVE_TRADING_ENABLED=0 \
  CODEXPOLY_IMAGE_REF \
  python -u -m cbr_trading.simulations.staging_earnings_shadow \
  --confirm STAGING_SHADOW
```

It persists a uniquely scoped synthetic fact after the parser boundary, runs
the real hosted source, numeric strategy, intent binding, and
`DryRunPreparedExecutor`, then disables the synthetic rule/profile and marks
the fact `SUPERSEDED`. The command reports only aggregate evidence and never
submits an order.

The MSTR equivalent retains its synthetic fact because the MSTR audit is
append-only. Its unique scope is not present in production rules:

```bash
docker run --rm \
  --network codexpoly-staging-backend \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=32m \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --mount type=bind,src=/home/codexdeploy/.config/codexpoly/secrets/staging/DATABASE_APP_PASSWORD,dst=/run/secrets/DATABASE_APP_PASSWORD,readonly \
  --env CODEXPOLY_ENVIRONMENT=staging \
  --env PRIMARY_DB_TARGET=server_int \
  --env DATABASE_HOST=postgres \
  --env DATABASE_PORT=5432 \
  --env DATABASE_NAME=codexpoly \
  --env DATABASE_USER=codexpoly_app \
  --env DATABASE_APP_PASSWORD_FILE=/run/secrets/DATABASE_APP_PASSWORD \
  --env RESOLUTION_ORCHESTRATOR_MODE=shadow \
  --env RESOLUTION_SUPERVISION_ENABLED=0 \
  --env CBR_LIVE_TRADING_ENABLED=0 \
  CODEXPOLY_IMAGE_REF \
  python -u -m cbr_trading.simulations.staging_mstr_btc_shadow \
  --confirm STAGING_MSTR_SHADOW
```

The smoke temporarily enables only `staging-mstr-smoke-*` profiles, expects
three hosted decisions, requires every result to be unattempted `DRY_RUN`,
and disables all temporary profiles before returning.

To remove trading-secret access after a preflight, recreate the service from
the base production file alone:

```bash
docker compose --file compose.yml \
  up --detach --force-recreate resolution-worker
```

`codexdeploy` performs production Docker operations through `sudo -n`.
Production secret values remain outside the normal workflow: use only the
reviewed install scripts, name-only checks, and least-privilege Compose mounts.
