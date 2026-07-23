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

`--apply` requires `CBR_ADMIN_DATABASE_URL`. The monitoring runtime
never imports this writer and continues to use `CBR_DATABASE_URL` for
read-only rule loading.
