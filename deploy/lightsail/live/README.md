# Guarded NVTS production activation

This procedure is for the first live earnings event:
`earnings:NVTS:2026Q2`. It does not authorize trading by itself. The final
transition from authenticated preflight to `live` remains an explicit
release-time decision.

## Fixed boundary

- Production image:
  `codexpoly@sha256:2c408499ddd01367fe097586346bd6cbe5073f5c82b8831d4d642c839cf31c30`
- Account: `abccbaq`
- Profile: `earnings-nvts-2026q2`
- Profile window: July 27, 2026 19:00 UTC through July 28, 2026 03:00 UTC
- Desired price for either outcome: `0.999`
- Quantity: `50`
- Maximum order quantity: `50`
- Maximum per-order notional: `50`
- Maximum aggregate prepared notional: `1000`
- Supervision: required in live mode
- Northflank earnings source, earnings orchestrator, and legacy SEC ingest:
  paused and scaled to zero

The existing Northflank `cbr-rate-trader` service is outside this procedure
and must not be stopped as part of the NVTS activation.

## Before the execution window

Run the disarmed invariant through the stdin-only production migration runner:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/codexpoly_ssh.ps1 `
  -StdinSqlFile deploy/lightsail/live/000_verify_nvts_disarmed.sql `
  sudo /usr/local/sbin/codexpoly-production-migrate
```

The check must succeed. A validated NVTS fact, an execution claim, an active
order group, a changed profile, or any enabled profile makes it fail closed.

Also confirm:

1. `earnings-worker`, base `resolution-worker`, and PostgreSQL are healthy.
2. The production trading secret name-only check is `ok: true`.
3. The Polymarket market is active, not closed, and still accepting orders.
4. Both outcome books load and have usable asks.
5. The official earnings time has not moved outside the checked-in window.

The public market page showing an order book is useful evidence, but the final
check must use the market API and authenticated order-book preflight.

## Guarded activation

Do not apply the activation SQL before July 27, 2026 19:00 UTC.

First stop the base resolution worker so it cannot consume an enabled profile
in shadow mode:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/codexpoly_ssh.ps1 `
  sudo -n docker stop `
  codexpoly-production-workers-resolution-worker-1
```

Enable only the exact checked-in NVTS profile:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/codexpoly_ssh.ps1 `
  -StdinSqlFile deploy/lightsail/live/001_enable_nvts_live.sql `
  sudo /usr/local/sbin/codexpoly-production-migrate
```

Immediately run the read-only prestart verifier:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/codexpoly_ssh.ps1 `
  -StdinSqlFile `
    deploy/lightsail/live/002_verify_nvts_live_prestart.sql `
  sudo /usr/local/sbin/codexpoly-production-migrate
```

If either command fails, apply the disarm SQL and return to the base stack.

## Authenticated preflight

Start the trading overlay with all submission switches off. The command must
provide the reviewed immutable image reference, the approved non-secret HTTP
user agent, and the fixed caps above.

Required effective values:

```text
RESOLUTION_ORCHESTRATOR_MODE=preflight
RESOLUTION_SUPERVISION_ENABLED=0
CBR_LIVE_TRADING_ENABLED=0
CBR_LIVE_MAX_ORDER_QTY=50
CBR_LIVE_MAX_NOTIONAL=50
CBR_LIVE_MAX_TOTAL_NOTIONAL=1000
```

Compose sources:

```text
/opt/codexpoly/production/apps/workers/compose.yml
/opt/codexpoly/production/apps/workers/compose.trading.yml
```

Require the sanitized aggregate readiness result:

```text
Hosted resolution ready mode=preflight profiles=1 templates=2
```

Failure to load either book, authenticate, verify the SAFE wallet, inspect
balance and allowance, load tick size, or pre-sign both outcomes aborts the
activation.

## Live transition

Only after the authenticated preflight and an explicit release-time approval,
recreate `resolution-worker` with the same Compose files and caps plus:

```text
RESOLUTION_ORCHESTRATOR_MODE=live
RESOLUTION_SUPERVISION_ENABLED=1
CBR_LIVE_TRADING_ENABLED=1
```

Require:

```text
Hosted resolution ready mode=live profiles=1 templates=2
```

There must be exactly one live resolution worker across all hosts.

## Fail-closed disarm

Before any order has been submitted:

1. Stop `codexpoly-production-workers-resolution-worker-1`.
2. Apply
   `deploy/lightsail/live/003_disable_all_resolution_profiles.sql`.
3. Recreate `resolution-worker` from the base `compose.yml` only.
4. Run `000_verify_nvts_disarmed.sql`.
5. Confirm the base resolution worker has only
   `DATABASE_APP_PASSWORD` in its name-only secret set.

The disarm SQL does not cancel remote orders. If an order was submitted, do
not stop supervision until the owned order group is terminal. Any manual
cleanup must inspect and cancel only the exact persisted order IDs; an
account-wide or market-wide cancellation is prohibited.
