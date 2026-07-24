# Polymarket live preflight

Run the full warmed preflight used by the continuous CBR runner:

```powershell
python -m cbr_trading.live --runner-preflight
```

It loads every active CBR rule, verifies the execution ledger, decrypts and
authenticates each account, checks collateral, and prepares both YES and NO
outcome tokens. It also pre-signs both possible GTC orders and warms the
database claim connections so that these operations are not on the
post-publication path. It never submits an order and does not require
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

The continuous runner prepares and signs all possible orders before polling.
After the release it evaluates the rules, acquires persistent idempotency
claims in parallel, and submits all orders for one account through one batch
request. Balance, wallet, tick-size, and market checks happen during warm-up,
not after the CBR title is detected.
