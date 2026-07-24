# Resolution trading architecture

This document records the contracts accepted for the new project. The legacy
repository at `C:\polymarket-bot` is a read-only reference and is not modified.

## Runtime flow

```text
ResolutionTradingCoordinator
    |
    +-> Source -> ResolutionSignal -> Strategy -> OrderIntent
    |                                             |
    +---------------------------------------------v
                                          PreparedExecutor
                                                 |
                                                 v
                                          OrderSupervisor
```

1. A `Source` acquires and parses one external publication. It emits
   source-neutral `ResolutionSignal` objects and never places orders.
2. A `Strategy` exposes all static `OrderTemplate` alternatives before the
   event. After a signal arrives, it selects templates and binds them into
   concrete, idempotent `OrderIntent` objects.
3. A `PreparedExecutor` prepares templates before polling. A stable
   `PreparationContext` binds that work to the expected source publication.
   Preparation may resolve accounts, assets, tick metadata, neg-risk,
   idempotency claims, and signatures. Execution accepts only selected
   intents whose signal and parameters match that prepared scope.
4. A successful execution returns an `ExecutionHandle`. Its
   `order_group_id` is the ownership boundary for every later cancellation.
5. `OrderSupervisor` handles post-submission lifecycle. A
   `RepriceOnTickChange` policy may cancel only the live order IDs owned by its
   group and submit replacements at the newly valid tick.

## Coordinator lifecycle

`cbr_trading.application.ResolutionTradingCoordinator` owns one event scope:

1. It verifies that the source and `PreparationContext` agree, gathers static
   templates from one or more strategies, rejects duplicate identities, and
   performs exactly one executor preparation.
2. `WAITING`, an unrelated signal, or a transient source exception leaves the
   prepared coordinator reusable for the next poll.
3. A signal matching both `source` and `scope_id` is evaluated by every
   configured strategy. Every selected intent must be the exact binding of a
   template included in preparation.
4. All selected intents are handed to the executor in one call. An empty
   selection is also handed over so the executor can release reservations.
5. A valid execution result completes the coordinator. Strategy contract
   errors, execution exceptions, and malformed execution results are terminal
   and are never retried automatically.

An explicit monitor-only preparation is allowed when an event has no active
order templates. It still resolves the source event through the same
coordinator, but cannot submit an order.

## Invariants

- Sources have no dependency on strategies or execution.
- Strategies are deterministic domain logic and perform no I/O.
- An `OrderIntent` is valid by construction; rejected rules are represented
  outside it.
- Exactly one sizing mode is used: share quantity or currency notional.
- Idempotency joins `signal_id` with `template_id`.
- Cancel/replace scope is always `order_group`, never every order on an asset.
- Domain and protocol packages depend only on the Python standard library.
- A prepared executor is single-use after a scope-valid execution attempt.
- Legacy result-count mismatches and exceptions after submission starts are
  reported as `AMBIGUOUS`, never silently retried.

## Compatibility checkpoint

The existing DTOs in `cbr_trading.pipeline` remain the production runner API
for the tested CBR executor. The new contracts are additive and migrate one
boundary at a time without changing live behavior.

The first adapters live in `cbr_trading.sources.cbr` and
`cbr_trading.strategies.cbr_rate_decision`:

- the canonical release URL produces a stable `signal_id`;
- the existing CBR comparison and decision-mode functions remain authoritative;
- every active rule exposes preparable YES and NO templates;
- the selected intent binds `signal_id` to the already prepared `template_id`;
- `CbrWarmPreparedExecutorAdapter` exposes the working warm CBR executor
  through the universal `PreparedExecutor` contract;
- preparation publishes only non-secret order metadata needed to match legacy
  prepared orders to universal templates;
- execution returns source-neutral results and an owned `order_group` handle;
- the real CBR source and strategy have an end-to-end coordinator contract
  test;
- the CBR production runner now composes `CbrResolutionSource`,
  `CbrRateDecisionStrategy`, `CbrWarmPreparedExecutorAdapter`, and
  `ResolutionTradingCoordinator`;
- dry-run and unavailable-trading branches implement the same
  `PreparedExecutor` contract, including monitor-only operation;
- legacy `PipelineOutcome` is now only a compatibility DTO for the existing
  JSON and Telegram format, not the runtime orchestration path;
- no database schema has changed.
