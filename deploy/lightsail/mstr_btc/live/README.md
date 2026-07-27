# Guarded MSTR July 21-27 production activation

This procedure covers the first live MSTR BTC announcement window. It does
not authorize trading by itself. The final transition from authenticated
preflight to `live` remains an explicit release-time decision.

## Fixed boundary

- Account: `abccbaq`
- Profiles:
  - `mstr-jul21-27-purchase-any`
  - `mstr-jul21-27-purchase-over-1000`
  - `mstr-jul21-27-sale-any`
- Preparation window: July 27, 2026 06:00 UTC through July 28, 2026
  04:00 UTC
- Desired price for either outcome: `0.999`
- Quantity: `50`
- Maximum order quantity: `50`
- Maximum per-order notional: `50`
- Maximum aggregate prepared notional: `1000`
- Supervision: required in live mode
- Source: the shared production SEC-API WebSocket, with the MSTR 8-K router
- Pinned pre-window holdings: `843775 BTC`

Only one live resolution worker may exist across all hosts. Northflank
earnings/resolution duplicates and the legacy SEC ingest must remain paused
and scaled to zero. The Lightsail `earnings-worker` remains running because it
owns the shared SEC source and persists the MSTR fact.

## Before the execution window

Run the read-only disarmed invariant:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/codexpoly_ssh.ps1 `
  -StdinSqlFile `
    deploy/lightsail/mstr_btc/live/000_verify_mstr_disarmed.sql `
  sudo -n /usr/local/sbin/codexpoly-production-migrate
```

The check fails if any profile is enabled; the exact MSTR profiles, account,
append-only audit schema, or pinned holdings changed; or a filing, fact,
claim, or nonterminal MSTR order group already exists.

Also confirm immediately before activation:

1. PostgreSQL, `earnings-worker`, and the base `resolution-worker` are healthy.
2. The SEC heartbeat reports `connected=True`, `watches=4`, and `errors=0`.
3. The trading secret name-only check reports `ok: true`.
4. All three markets remain active, open, and accepting orders.
5. Both outcomes of all three markets load with tick `0.01` or `0.001` and
   minimum size no greater than `50`.
6. Northflank has no live earnings/resolution or legacy SEC duplicate.
7. The production source heartbeat reports both the SEC stream connected and
   the Strategy Ledger poller connected, with no Ledger rejection or error.

## No-submit supervision smoke

Run this from the base production `resolution-worker` image while all profiles
are disabled. The base service must have only the database secret mounted:

```text
python -u -m cbr_trading.simulations.production_supervision_smoke \
  --confirm PRODUCTION_MSTR_SUPERVISION_NO_SUBMIT \
  --duration 3
```

The smoke refuses live mode, refuses enabled supervision, refuses live
trading, and refuses trading-secret mounts. It:

- verifies the production supervision schema and absence of pending work;
- starts and stops the real background supervision runtime;
- loads all six public MSTR outcome books;
- keeps a real public market-channel subscription alive for the requested
  interval;
- uses a no-submit supervisor with no authenticated order gateway.

Require `ok=true`, `runtime_started=true`,
`market_channel_connected=true`, and every order-action flag `false`.

## Guarded activation

Do not apply the activation SQL before July 27, 2026 06:00 UTC.

First stop the base resolution worker so it cannot load an enabled profile in
shadow mode:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/codexpoly_ssh.ps1 `
  sudo -n docker stop `
  codexpoly-production-workers-resolution-worker-1
```

Enable exactly the three checked-in MSTR profiles:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/codexpoly_ssh.ps1 `
  -StdinSqlFile `
    deploy/lightsail/mstr_btc/live/001_enable_mstr_live.sql `
  sudo -n /usr/local/sbin/codexpoly-production-migrate
```

Immediately run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/codexpoly_ssh.ps1 `
  -StdinSqlFile `
    deploy/lightsail/mstr_btc/live/002_verify_mstr_live_prestart.sql `
  sudo -n /usr/local/sbin/codexpoly-production-migrate
```

If either command fails, apply the common disarm SQL and return to the base
stack.

## Final authenticated preflight

Use the reviewed immutable image through `compose.yml` plus
`compose.trading.yml` with:

```text
RESOLUTION_ORCHESTRATOR_MODE=preflight
RESOLUTION_SUPERVISION_ENABLED=0
CBR_LIVE_TRADING_ENABLED=0
CBR_LIVE_MAX_ORDER_QTY=50
CBR_LIVE_MAX_NOTIONAL=50
CBR_LIVE_MAX_TOTAL_NOTIONAL=1000
```

Run:

```text
python -u -m cbr_trading.simulations.production_mstr_btc_preflight \
  --confirm PRODUCTION_MSTR_AUTHENTICATED_PREFLIGHT \
  --all-profiles
```

Require three enabled profiles, six prepared alternatives, maximum prepared
notional `297`, maximum selected notional `149.85`, and:

```text
order_submitted=false
source_fact_polled=false
executor_execute_called=false
```

Warm preparation must create no execution claim. Claims are reserved
atomically only after a matching persisted signal and immediately before
submission. The executor reserves all six prepared alternatives in one
transaction, submits the three selected templates, marks those claims
`EXECUTED`, and marks the three unselected alternatives `EXPIRED`. A
pre-signal restart is therefore safe. Any claim that appears before live
startup is a blocker.

## Live transition

Only after the authenticated preflight and explicit release-time approval,
recreate `resolution-worker` from the same immutable image and Compose files
with:

```text
RESOLUTION_ORCHESTRATOR_MODE=live
RESOLUTION_SUPERVISION_ENABLED=1
CBR_LIVE_TRADING_ENABLED=1
CBR_LIVE_MAX_ORDER_QTY=50
CBR_LIVE_MAX_NOTIONAL=50
CBR_LIVE_MAX_TOTAL_NOTIONAL=1000
```

Require:

```text
Hosted MSTR resolution ready mode=live profiles=3 templates=6
```

Before the signal, the claims table must remain empty for all three scopes.
After a signal, a duplicate worker must lose the atomic claim race before any
order submission. A crash after reservation remains fail-closed because the
remote submission result can be ambiguous.

## Post-execution verification

After the three profiles report `COMPLETED`, inspect the three exact persisted
order IDs through the authenticated read-only audit:

```text
python scripts/production_mstr_order_audit.py
```

The script never prints order IDs or secrets. Require `ok=true`,
`order_count=3`, `all_terminal=true`, and three `FILLED` states with zero
remaining quantity.

Then run the database invariant:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/codexpoly_ssh.ps1 `
  -StdinSqlFile `
    deploy/lightsail/mstr_btc/live/003_verify_mstr_post_execution.sql `
  sudo -n /usr/local/sbin/codexpoly-production-migrate
```

It requires one accepted SEC fact, six terminal claims
(`3 EXECUTED + 3 EXPIRED`), three selected `NO` submissions at their
tick-aligned prices, and terminal supervision state.

## Fail-closed disarm

Before any order has been submitted:

1. Stop `codexpoly-production-workers-resolution-worker-1`.
2. Apply
   `deploy/lightsail/live/003_disable_all_resolution_profiles.sql`.
3. Recreate `resolution-worker` from the base Compose file only.
4. Run `000_verify_mstr_disarmed.sql`.
5. Confirm the base worker has only `DATABASE_APP_PASSWORD` mounted.

The disarm SQL does not cancel remote orders. If an order was submitted, do
not stop supervision until the exact persisted order group is terminal.
Manual cleanup may inspect and cancel only the persisted order IDs; an
account-wide or market-wide cancellation is prohibited.

The hosted worker loads profiles at startup rather than hot-reloading them.
If another profile window opens while MSTR is still waiting, use a separately
reviewed combined activation and restart sequence. Never enable a new profile
behind an already running worker and assume it was loaded.
