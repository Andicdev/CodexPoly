# Polymarket live preflight

Run the full warmed preflight used by the continuous CBR runner:

```powershell
python -m cbr_trading.live --runner-preflight
```

It loads every active CBR rule, verifies the execution ledger with the exact
`PENDING` reservation insert inside a rolled-back transaction, decrypts and
authenticates each account, checks collateral, and prepares both YES and NO
outcome tokens. It also pre-signs both possible GTC orders. It never submits
an order and does not require
`CBR_LIVE_TRADING_ENABLED=1`; the output reports whether that final switch is
currently enabled.

Preview the only active CBR fast-path rule:

```powershell
python -m cbr_trading.live --action YES
```

The preview reads the rule and account in read-only database transactions,
fetches the current public order book, and prints all safety blockers. It does
not decrypt the private key or authenticate with Polymarket.

After adding the existing `ACCOUNTS_MASTER_KEY`, verify authentication, wallet
type, collateral balance, and a fresh order book without submitting an order:

```powershell
python -m cbr_trading.live --action YES --auth-check
```

This authenticated check may derive or create CLOB API credentials, but it
does not call the order submission endpoint.

Real submission additionally requires:

- `CBR_LIVE_TRADING_ENABLED=1`;
- `CBR_LIVE_ALLOWED_ACCOUNT` matching the stored account name;
- `CBR_LIVE_MAX_ORDER_QTY` and `CBR_LIVE_MAX_NOTIONAL`;
- `CBR_LIVE_POST_ONLY=0` for an ordinary aggressive GTC limit order;
- the existing Fernet `ACCOUNTS_MASTER_KEY`;
- both `--apply` and `--confirm-live-order`.

Example (do not run without checking the preview first):

```powershell
python -m cbr_trading.live --action YES --apply --confirm-live-order
```

All orders from this utility are limit BUY and GTC. With
`CBR_LIVE_POST_ONLY=0`, available asks at or below the limit execute
immediately and any unfilled remainder rests at the configured limit until it
is cancelled or the market closes. Set `CBR_LIVE_POST_ONLY=1` only when
maker-only behavior is explicitly required; such an order is skipped if it
would cross the current ask.

Before every production event, run one small real order through the exact
continuous-runner path. This is intentionally different from `--apply`: it
prepares both outcomes, reserves both idempotency rows, sends the selected
outcome with the batch endpoint, records its result, and expires the
unselected reservation.

```powershell
python -m cbr_trading.live `
  --full-path-live-test `
  --test-run-id pre-event-001 `
  --rule-id 102 `
  --action NO `
  --quantity 5 `
  --limit-price 0.10 `
  --confirm-live-order
```

The live switch and all safety caps must be armed. Quantity, price, rule,
action, confirmation, and a 3-64 character test id are mandatory. The test id
is part of persistent idempotency: rerunning the same command with the same id
fails before submission instead of placing a duplicate. Use a new id only for
an intentionally new real test.

The continuous runner prepares, signs, and persistently reserves all possible
orders before polling. After the release it evaluates the rules and immediately
submits all selected orders for one account through one batch request. There
are no database, balance, book, signing, or Telegram calls between detection
and the batch request. Database result updates and Telegram happen afterward.

## Order supervision status

The source-neutral persistent supervisor and
`PolymarketSupervisionOrderGateway` are connected to the CBR runner behind the
disabled-by-default `RESOLUTION_SUPERVISION_ENABLED` gate. The gateway uses
only exact order-ID batch cancellation and rechecks the authenticated account,
order book, target tick, minimum size, and live safety caps before a
replacement. It reads each exact order both before and after cancellation.
Replacement uses only the final unfilled quantity; a full fill creates no
replacement, and an unconfirmed post-cancel state fails closed.

The supervisor also has a bounded background recovery scan for stale
`REPRICING` and `FAILED` groups. It only reads exact persisted order IDs and
never cancels or submits an order during recovery. A persisted `UNKNOWN`
replacement can be promoted only after its price and size are verified
against terminal source orders. Missing IDs, overlapping live generations, or
sizing mismatches are quarantined for manual review; transient CLOB lookup
failures remain retryable.

The public `PolymarketMarketChannel` subscribes to exact token IDs loaded from
active persisted order groups. It sends a configured tick transition to the
same supervisor when any of these proves the new tick:

- the explicit WebSocket `tick_size_change` event;
- `tick_size` on a full order-book event;
- a nonzero real book or price-change level, such as `0.999`, that is invalid
  at `0.01` and valid at the configured `0.001`.

It never concludes that the old tick remains active merely because current
prices happen to align to the old grid. The official SDK owns WebSocket
heartbeat, reconnect, and subscription resend. A reusable periodic-book entry
point feeds the same deduplicating detector, although no polling scheduler is
started in this checkpoint.

When enabled, the supervision runtime starts before live executor preparation,
refreshes the active watch set, and runs recovery on a separate interval. A
known submitted repricing order is registered synchronously. If that database
registration fails, the result is reported as `AMBIGUOUS`, not `SUBMITTED`.
After the release result is printed, the runner remains alive while an active
or automatically recoverable group still exists.

Required non-secret configuration:

```text
RESOLUTION_SUPERVISION_ENABLED=1
RESOLUTION_SUPERVISION_WATCH_REFRESH_SEC=2
RESOLUTION_SUPERVISION_RECONCILE_SEC=30
RESOLUTION_SUPERVISION_STALE_SEC=300
RESOLUTION_SUPERVISION_BATCH_SIZE=100
```

The existing live-trading account and safety configuration is still required.
The runner never applies database migrations. Apply migrations 001 and 002
through the controlled deployment process before enabling the gate;
`ensure_ready()` blocks live preparation if any required table or column is
missing. For the configured primary database, both migrations were applied and
independently verified on 2026-07-24. The four new tables were empty after
creation, all required indexes and foreign keys were present, and the legacy
schema was unchanged.

A live rule with `RepriceOnTickChange` is deliberately non-submitting while
the gate is disabled. The warm executor keeps `desired_price` separate from
the initially signed price: a desired BUY price of `0.999` is prepared at
`0.99` while tick `0.01` is active, then the supervisor replaces it at `0.999`
after tick `0.001` is confirmed.
