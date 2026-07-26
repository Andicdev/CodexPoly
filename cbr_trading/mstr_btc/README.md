# MSTR BTC resolution flow

The MSTR source reuses the shared SEC WebSocket transport. An accepted
holdings-first fact is persisted in the append-only MSTR audit tables and
fans out into three independent market scopes:

- any BTC purchase;
- a strict purchase greater than 1000 BTC;
- any BTC sale.

The source owns fact interpretation only. It does not import a trading
account, build an `OrderIntent`, or call an executor. The separate hosted
composition binds each signal scope to its own execution profile and numeric
strategy without adding trading dependencies to the source service.

## Hosted composition

`MstrBtcHostedResolutionWorker` is part of the separate
`resolution-worker` service. It:

1. loads only enabled profiles whose source is `mstr_btc_resolution`;
2. verifies their `condition_id` and Polymarket URL against the checked-in
   market bindings;
3. reads only `VALIDATED` facts for the required weekly scope;
4. creates one source, numeric strategy, and prepared executor per market;
5. expires a prepared profile without consuming a late fact when its window
   closes.

The production profiles are seeded separately and remain `DISABLED`. Their
defaults are desired price `0.999` on both outcomes, quantity `50`, and one
tick reprice from `0.01` to `0.001`.

## Non-submitting end-to-end simulation

Run:

```text
python -m cbr_trading.simulations.mstr_btc_resolution
```

The simulation bypasses document parsing and does not use a database,
network, account key, or persisted execution profile. Three deterministic
facts cover:

- a 1500 BTC purchase: `YES / YES / NO`;
- an exact 1000 BTC purchase: `YES / NO / NO`;
- a 32 BTC sale: `NO / NO / YES`.

For every scenario, three independent coordinators exercise:

```text
MstrBtcResolutionSource
    -> ResolutionSignal
    -> NumericThresholdStrategy
    -> OrderIntent
    -> DryRunPreparedExecutor
```

Every market prepares both alternatives at desired price `0.999`, quantity
`50`, with the single `0.01 -> 0.001` tick-reprice policy. Synthetic signal
IDs are deliberately outside production scopes, execution is always
`DRY_RUN`, and no production idempotency claim is created.

The staging persisted-fact smoke uses a real append-only audit row but a
unique `staging-mstr-smoke-*` weekly scope:

```text
python -m cbr_trading.simulations.staging_mstr_btc_shadow \
  --confirm STAGING_MSTR_SHADOW
```

It temporarily enables three synthetic profiles, runs the hosted worker
through `DryRunPreparedExecutor`, and disables the profiles in `finally`.
The synthetic audit row remains immutable by design and cannot collide with
a production rule or execution claim.
