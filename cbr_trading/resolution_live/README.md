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

## Controlled live test

The submitting path is deliberately gated behind all live safety settings and
every explicit command-line acknowledgement:

```powershell
python -m cbr_trading.resolution_live `
  --rule-id 103 `
  --live-test `
  --test-run-id UNIQUE_RUN_ID `
  --quantity 5 `
  --limit-price 0.90 `
  --confirm-live-order `
  --cancel-after-test
```

The quantity and price are one-shot overrides; the database rule remains
unchanged. Before polling, the executor authenticates, refreshes the market,
and pre-signs the order without creating a claim. After the manual signal
selects the intent, it atomically reserves `scope_id + template_id` in
`resolution_execution_claims` immediately before submission. A repeated
`test-run-id` cannot submit again.

After a successful post, the command inspects only the returned order ID,
cancels only that ID if it is still open, confirms `CANCELLED` or `FILLED`,
and appends the cleanup outcome to the same execution claim. An ambiguous
submission without an order ID or an unconfirmed cleanup returns failure for
manual investigation; it never broadens cancellation to other account orders.

`ManualResolutionSource` is used only by this controlled command. A production
source replaces it without changing the strategy, intent, or executor
contracts.

## Live smoke checkpoint

On 2026-07-24, test scope
`opus-103-smoke-20260724-a8a3857` exercised rule 103 with a one-shot post-only
BUY YES order for 5 shares at `0.90`:

- preparation and atomic claim reservation succeeded;
- Polymarket accepted one order and its first exact inspection was `OPEN`;
- cancellation was requested and acknowledged only for that returned order
  ID;
- the final exact inspection was `CANCELLED`;
- the cleanup audit was appended to the `EXECUTED` claim.

The persistent rule remained configured for 100 shares at `0.90`; the smoke
quantity was not written to `monitored_news`.
