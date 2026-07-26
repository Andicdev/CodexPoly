# MSTR BTC resolution flow

The MSTR source reuses the shared SEC WebSocket transport. An accepted
holdings-first fact is persisted in the append-only MSTR audit tables and
fans out into three independent market scopes:

- any BTC purchase;
- a strict purchase greater than 1000 BTC;
- any BTC sale.

The source owns fact interpretation only. It does not import a trading
account, build an `OrderIntent`, or call an executor. A later hosted
composition will bind each signal scope to its own execution profile and
numeric strategy.

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
