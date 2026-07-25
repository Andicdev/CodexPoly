# CodexPoly earnings workers on Lightsail

## Service boundary

The worker stack contains exactly two private services built from the same
reviewed CodexPoly image:

- `earnings-worker` runs `python -u -m cbr_trading.earnings`;
- `resolution-worker` runs
  `python -u -m cbr_trading.resolution_hosted`.

Neither service publishes a host port. Both join the existing internal
PostgreSQL network and connect to `postgres:5432` as `codexpoly_app`.
Both use the AWS link-local resolver `169.254.169.253`; this avoids forwarding
external lookups from rootless Docker to the host-only systemd-resolved stub.
`earnings-worker` receives the SEC credential but never receives a trading
credential. The base `resolution-worker` starts in `shadow` and receives only
the application database password.

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
TRADING_ACCOUNT_WALLET_ADDRESS
CBR_LIVE_MAX_ORDER_QTY
CBR_LIVE_MAX_NOTIONAL
CBR_LIVE_MAX_TOTAL_NOTIONAL
```

The wallet is the existing proxy wallet for `abccbaq`; the account venue is
`polymarket_clob` and its signature type is `2`. Keep the wallet in
operator-controlled non-secret deployment configuration. Do not put a private
key, master key, database password, or API token in that configuration.

The overlay defaults to:

```text
RESOLUTION_ORCHESTRATOR_MODE=preflight
RESOLUTION_SUPERVISION_ENABLED=0
CBR_LIVE_TRADING_ENABLED=0
```

Live mode therefore requires explicit values for all three guards, including
`RESOLUTION_SUPERVISION_ENABLED=1` and
`CBR_LIVE_TRADING_ENABLED=1`.

## Account secret installation

The production account has no `trading_accounts` row. An infrastructure
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
7. Enable one in-window profile and recreate `resolution-worker` with the
   production trading overlay in preflight mode.
8. Return the profile to `DISABLED` after the authenticated preflight.
9. Enable live mode only after explicit approval and after the Northflank live
   resolution worker is stopped.

Only one live resolution worker may exist across Northflank and Lightsail. The
two databases do not share execution claims, so simultaneous live workers are
not protected from one another by idempotency.

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

To remove trading-secret access after a preflight, recreate the service from
the base production file alone:

```bash
docker compose --file compose.yml \
  up --detach --force-recreate resolution-worker
```

The infrastructure administrator performs production Docker commands.
`codexdeploy` can validate staging and apply approved database migrations but
does not control the production Docker daemon.
