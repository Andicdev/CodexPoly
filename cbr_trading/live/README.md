# Manual Polymarket live preflight

This module is intentionally separate from the continuous CBR runner. The
runner remains dry-run until the manual order lifecycle has been verified.

Preview the only active CBR fast-path rule:

```powershell
python -m cbr_trading.live --action YES
```

The preview reads the rule and account in read-only database transactions,
fetches the current public order book, and prints all safety blockers. It does
not decrypt the private key or authenticate with Polymarket.

Real submission additionally requires:

- `CBR_LIVE_TRADING_ENABLED=1`;
- `CBR_LIVE_ALLOWED_ACCOUNT` matching the stored account name;
- `CBR_LIVE_MAX_ORDER_QTY` and `CBR_LIVE_MAX_NOTIONAL`;
- `CBR_LIVE_POST_ONLY=1`;
- the existing Fernet `ACCOUNTS_MASTER_KEY`;
- both `--apply` and `--confirm-live-order`.

Example (do not run without checking the preview first):

```powershell
python -m cbr_trading.live --action YES --apply --confirm-live-order
```

All orders from this utility are BUY, post-only, and GTC. Post-only prevents
immediate execution when the order would cross the book. A resting GTC order
can still fill later until it is cancelled or the market closes.
