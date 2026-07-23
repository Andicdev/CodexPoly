# CBR rule administrator

This command resolves the three active markets of a Bank of Russia
Polymarket event and builds the stable `decrease`, `no_change`, and
`increase` rules.

Preview only (default):

```powershell
python -m cbr_trading.admin `
  --event-url "https://polymarket.com/event/bank-of-russia-decision-in-july" `
  --account-name "account-name"
```

Write the previewed rules:

```powershell
python -m cbr_trading.admin `
  --event-url "https://polymarket.com/event/bank-of-russia-decision-in-july" `
  --account-name "account-name" `
  --apply
```

`--apply` uses `CBR_ADMIN_DATABASE_URL` when configured. Otherwise it
uses the selected primary database URL (`DATABASE_URL_SERVER_INT` on
Render, `DATABASE_URL_SERVER_EXT` locally and on a VPS). The monitoring
runtime never imports this writer.
