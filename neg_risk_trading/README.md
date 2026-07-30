# Neg-risk trading

This package is the isolated research and shadow-trading foundation for the
second trading account. It does not import the existing live strategy
composition and does not place, sign, cancel, or prepare an order.

## First strategy

The first implemented route is a strict full-basket maker-sell cycle for a
standard (non-augmented) negative-risk event:

1. one complete YES basket is treated as costing 1 unit of collateral;
2. one selected YES outcome is offered as a resting maker sell;
3. after that maker fill, the same quantity of every other YES outcome is
   sold into the bid books;
4. every hedge level uses its own configured taker fee;
5. the route is available only when every hedge leg has sufficient depth.

September Fed is the initial event:

```text
fed-decision-in-september-762
```

The evaluator uses `Decimal`, rounds every aggregate hedge-level fee upward to
the documented five-decimal fee precision, and reports maker rebate only as
an estimate. A positive result does not include gas, settlement failure,
latency, adverse selection, or the eventual share of liquidity rewards.

## Safety boundary

- Gamma and CLOB order books are public, unauthenticated endpoints.
- All five YES books are fetched in one `POST /books` request.
- Missing fee metadata, a partial book set, a slow batch response, augmented
  events, crossing maker prices, unsupported fee formulas, and insufficient
  hedge depth fail closed.
- CLOB book timestamps are last-change telemetry and are not assumed to be a
  common batch clock. The shadow REST snapshot is bounded by the duration of
  its single `POST /books` request. Live execution will require the maintained
  WebSocket books and their hashes.
- The market WebSocket subscribes to both YES and NO asset IDs for every
  component market. A connection epoch is not `READY` until every asset has
  supplied a full `book`; malformed updates, timestamp regressions, heartbeat
  loss, disconnects, and incomplete reconnects are not tradable state.
- Liquidity reward eligibility is only a top-of-book screening value. The
  authoritative formula uses the size-cutoff-adjusted midpoint and the
  maker's relative score.
- The JSON command output contains public market metadata only.

Run a current shadow snapshot:

```powershell
python -m neg_risk_trading `
  --event fed-decision-in-september-762 `
  --quantities 20,50,100,200,500
```

Validate the public REST bootstrap and the complete WebSocket initial dump:

```powershell
python -m neg_risk_trading.stream_probe `
  --event fed-decision-in-september-762
```

The continuous recorder runs only with the isolated database configured:

```powershell
python -m neg_risk_trading.recorder_main
```

It never migrates the schema at startup. Apply the checked-in migration
explicitly first. Public stream messages enter a bounded in-memory queue and
are written in batches by a separate task; database I/O is not performed by
the WebSocket event callback.

## Full neg-risk catalog

The catalog scanner continuously traverses the official Gamma
`/markets/keyset` endpoint and filters the complete active result locally.
It groups neg-risk markets by their linked event and stores:

- current event and market volume windows, liquidity, and open interest;
- fee type, exact fee schedule, rebate rate, and derived fee category;
- current tick, minimum order size, price, spread, and accepting-order state;
- reward size/spread terms, explicit `Other` legs, and sub-one-percent tails;
- transparent fee/tick profiles and `READY_FOR_L2_REPLAY`,
  `REVIEW_REQUIRED`, or `NOT_TRADABLE` screening status.

The status is only a metadata-completeness screen. It is not an arbitrage
signal and does not replace L2 replay, fill probability, or risk review.
Pages are written to scan-scoped staging tables and promoted in one database
transaction only after cursor exhaustion, so readers never see a partial
catalog as current.

Run the continuous scanner:

```powershell
python -m neg_risk_trading.catalog_main
```

Read a safe JSON snapshot of the latest completed scan, category/profile
totals, and the highest-ranked metadata-complete events:

```powershell
python -m neg_risk_trading.catalog_report --top 20
```

The database views `neg_risk_catalog_ranked_events` and
`neg_risk_catalog_category_summary` expose the current ranked list and
category totals without requiring raw Gamma payload access.

## Resting-order retention

Queue position is treated as an asset. A temporary edge reduction, a long
queue, or a better displayed quote will not by itself imply cancellation.
The shadow engine records a lower and upper queue-ahead bound from aggregate
L2 changes and exact own fills will later come from the authenticated user
channel.

The keep/cancel policy will use hysteresis and separate soft economic changes
from hard safety invalidation. No live cancellation rule is implemented yet.
It will be calibrated from recorded fill probability, adverse markouts, hedge
depth, and time spent in queue.

## Development sequence

1. Completed: deterministic event/book parsing and depth-aware route
   evaluation.
2. Completed foundation: all-asset WebSocket initial dump, local L2 updates,
   tick changes, readiness epochs, resync states, and queue-ahead bounds.
3. Completed locally: append-only PostgreSQL persistence and a bounded
   continuous shadow recorder for the isolated `codexpoly_neg_risk` database.
4. Completed: staging recorder and full active neg-risk Gamma catalog.
5. Derive fill probability, trade flow, post-fill markouts, and select events
   for dedicated L2 recording from catalog rankings.
6. Implement prepared full-basket inventory and a paper executor.
7. Add authenticated preflight, persistent idempotency, exact-order
   supervision, and settlement recovery.
8. Keep live trading disabled until the complete preflight and risk review.

Relevant Polymarket documentation:

- https://docs.polymarket.com/concepts/negative-risk
- https://docs.polymarket.com/trading/fees
- https://docs.polymarket.com/trading/orderbook
- https://docs.polymarket.com/programs/maker-rebates
- https://docs.polymarket.com/programs/liquidity-rewards
- https://docs.polymarket.com/market-data/fetching-markets
