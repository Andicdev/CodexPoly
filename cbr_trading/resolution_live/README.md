# Source-neutral resolution preflight

Run one active `fixed_outcome` rule through the universal contracts without
submitting an order:

```powershell
python -m cbr_trading.resolution_live --rule-id 103
```

The command:

1. loads exactly one active `monitored_news` row by ID without applying the
   CBR ticker or metric filter;
2. builds one `OrderTemplate` for the configured fixed outcome;
3. creates an explicit manual `ResolutionSignal` in the same source and scope;
4. authenticates the configured account, refreshes the public and
   authenticated books, verifies tick, minimum size, balance, and safety caps;
5. pre-signs the GTC order locally and discards it without posting;
6. sends the selected intent only to a non-submitting `DRY_RUN` executor.

`CBR_LIVE_TRADING_ENABLED` may remain disabled. The command reports its state
but never calls an order submission endpoint, never reserves an execution
claim, and never mutates the rule. It still requires the existing allowed
account, safety caps, encrypted account record, and `ACCOUNTS_MASTER_KEY`
because authenticated preparation is the behavior under test.

This checkpoint deliberately stops before source-neutral idempotency and
submission. A production source must replace `ManualResolutionSource`, and a
submitting executor must reserve the exact signal/template identity before it
can post the already prepared order.
