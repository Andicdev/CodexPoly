# Neg-risk bid-side replay staging checkpoint

Date: 2026-07-31

## Scope

This checkpoint advances the September FED neg-risk work without enabling
orders:

- adds a strict depth-aware `MAKER_BUY` full-basket route alongside the
  existing `MAKER_SELL` route;
- applies each hedge fill's configured taker fee and keeps estimated maker
  rebate separate from strict base profit;
- persists the exact public event, market, fee, reward, asset, tick, and
  minimum-size contract used by each new recorder session;
- replays append-only WebSocket payloads deterministically without consulting
  current Gamma or CLOB state;
- records value-safe stream anomalies and resynchronizes semantic
  top-of-book mismatches from a fresh all-asset initial dump;
- discards asset-less `new_market` notices before persistence.

The two-market `0.55 + 0.44` example is an executable test case. At quantity
`200`, the gross basket costs `198`, but the configured taker fee is `2.464`.
Strict base profit is therefore `-0.464`. The estimated maker rebate is
reported independently and is never required for a route to pass the strict
profit screen.

## Deployment

The deployed source revision is `daff963`. Its clean `git archive` SHA-256 is:

```text
823c76ffca507582f81fec793b7d6ffa873a28bb944b6a42e0c608fe61b13f28
```

The rootless Docker image is pinned by immutable ID:

```text
sha256:2d11554ef95125ec97cb55bf3c486b86bf6ddb865012034fa75bd603729f8d14
```

The OCI revision label is `daff963`.

Migration `003_add_bid_routes_and_stream_anomalies.sql` was applied only to
the staging `codexpoly_neg_risk` database. Only `neg-risk-recorder` was
recreated. The catalog container remained on its prior immutable image.
Both containers report `running` with restart count zero. Production was not
changed.

## Initial deterministic replay

The first new session reached `READY` with one uninterrupted connection
epoch. An initial 37-second replay covered:

```text
source_messages=363
applied_updates=372
evaluated_messages=39
connection_epochs=1
```

For quantity `200`, none of the five `MAKER_BUY` routes was positive before or
after the estimated rebate. The best observed strict maker-buy edge was:

```text
increase_25=-0.0289662 per share
no_change=-0.0338346 per share
```

Two `MAKER_SELL` routes were positive during part of this very short window:

```text
increase_25 average=0.0032412179 maximum=0.0052925 per share
no_change  average=0.0023771064 maximum=0.0050925 per share
```

Their average displayed queue ahead was approximately `12,647` and `13,126`
shares respectively. This is book-state opportunity telemetry, not expected
profit: it does not yet model fill probability, adverse selection, queue
survival, or post-fill hedge slippage beyond displayed depth.

## Catalog state

The concurrently running catalog's latest complete traversal reported:

```text
gamma_markets=118256
neg_risk_markets=46927
events=7375
ready_for_l2_replay=6005
skipped_markets=0
fee_free_ready_events=16
```

September FED remained global rank 1 in the metadata screen. The catalog
screen is not a strategy signal; it identifies candidates for dedicated L2
recording and replay.

## Safety and verification

- The recorder remains mandatory `SHADOW` with
  `live_orders_enabled=false`.
- No order builder, signer, private key, CLOB credential, or authenticated
  user channel is present in this service.
- The observation schema and active-recorder checks passed after migration.
- The local and clean-image secret scans passed.
- The complete Python 3.12 suite passed: `1026` tests with one skip.

The next evidence gate is a longer two-direction replay window, followed by
trade-flow, queue-fill probability, queue-survival, and post-fill markout
measurement. No paper executor should be added until those measurements can
reject superficially positive but unfillable routes.
