# Earnings shadow source

This package implements only the source side of the resolution architecture:

```text
SEC WebSocket / company IR
    -> EarningsDocumentCandidate
    -> company parser
    -> EarningsFactCandidate
    -> EarningsResolutionSource
    -> ResolutionSignal
```

It deliberately has no dependency on a strategy, `OrderIntent`, or
`PreparedExecutor`. A signal emitted here cannot place an order unless a
separate later composition explicitly wires it to those layers.

## NVTS checkpoint

The checked-in NVTS rule is a `SHADOW` configuration for fiscal 2026 Q2:

- stable scope: `earnings:NVTS:2026Q2`;
- expected period end: 2026-06-30;
- official release time: 2026-07-27 17:00 ET;
- primary metric: non-GAAP EPS;
- comparison and strike retained for the future strategy: `> -0.04`;
- standard cent rounding;
- official-company source first, with fallback timing recorded but not yet
  implemented.

The SEC router accepts only an initial `8-K` with `Item 2.02` and one
`EX-99.1` press-release exhibit for the watched ticker/CIK. It rejects
amendments, unrelated filings, ambiguous exhibits, and identity mismatches.

The Navitas parser requires the expected fiscal period and the exact
reconciliation row for non-GAAP net loss per share. Missing non-GAAP EPS
returns `NO_MATCH`; it never produces a premature `NO` resolution.

## Explicit database setup

Normal runners never apply migration 004. Check readiness with:

```text
python -m scripts.manage_earnings_schema
```

Explicitly create the three additive tables and save the NVTS shadow rule:

```text
python -m scripts.manage_earnings_schema --apply --seed-nvts-shadow
```

The seed remains `SHADOW` and does not create source events, fact candidates,
execution claims, or orders.

## Hosted shadow worker

Run the long-lived source worker with:

```text
python -u -m cbr_trading.earnings
```

Before opening the WebSocket, run the presence/schema/rule preflight:

```text
python -m scripts.check_earnings_shadow_runtime
```

It reports only the selected database target, credential presence, active
scope names, watch count, and missing parser names.

It performs this loop:

1. verifies migration 004 without applying migrations;
2. loads only `SHADOW` and `WATCHING` rules;
3. opens one SEC WebSocket connection;
4. persists a deduplicated source event;
5. downloads only a bounded public `https://*.sec.gov` exhibit;
6. runs the configured company parser;
7. persists a validated fact and logs a shadow `ResolutionSignal`.

The worker rejects any mode except `shadow`. It does not import a strategy,
account repository, Polymarket client, `OrderIntent`, or `PreparedExecutor`.
Rule changes are picked up on the next reconnect or service restart.

Required confidential runtime values:

- a configured primary database URL;
- one of `SEC_API_KEY`, `SEC_API_IO_KEY`, or `SEC_API_STREAM_KEY`.

Keep both in a restricted platform Secret Group. Do not attach trading-account
or Polymarket signing secrets to the shadow source service.

## Historical replay

Run the parser against four official Navitas IR releases without storing the
documents:

```text
python -m scripts.replay_navitas_earnings
```

## End-to-end synthetic resolution

Before the real release, inject a normalized EPS fact after the parser and run
the real source, numeric threshold strategy, and authenticated executor
preflight:

```text
python -m cbr_trading.simulations.earnings_resolution --eps -0.03
python -m cbr_trading.simulations.earnings_resolution --eps -0.04
```

For the NVTS rule these cases must select `YES` and `NO`, respectively. The
simulator prepares and pre-signs both market outcomes, then returns one
`DRY_RUN` result for the selected outcome. It never submits an order.

The injected fact is kept only in memory: no source event or fact candidate is
stored. Every run also uses a unique synthetic signal scope, leaving the real
`earnings:NVTS:2026Q2` idempotency scope untouched for Monday.
