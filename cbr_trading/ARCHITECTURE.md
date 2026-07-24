# Resolution trading architecture

This document records the contracts accepted for the new project. The legacy
repository at `C:\polymarket-bot` is a read-only reference and is not modified.

## Runtime flow

```text
Source -> ResolutionSignal -> Strategy -> OrderIntent -> PreparedExecutor
                                                        |
                                                        v
                                                 OrderSupervisor
```

1. A `Source` acquires and parses one external publication. It emits
   source-neutral `ResolutionSignal` objects and never places orders.
2. A `Strategy` exposes all static `OrderTemplate` alternatives before the
   event. After a signal arrives, it selects templates and binds them into
   concrete, idempotent `OrderIntent` objects.
3. A `PreparedExecutor` prepares templates before polling. Preparation may
   resolve accounts, assets, tick metadata, neg-risk, idempotency claims, and
   signatures. Execution accepts only selected intents.
4. A successful execution returns an `ExecutionHandle`. Its
   `order_group_id` is the ownership boundary for every later cancellation.
5. `OrderSupervisor` handles post-submission lifecycle. A
   `RepriceOnTickChange` policy may cancel only the live order IDs owned by its
   group and submit replacements at the newly valid tick.

## Invariants

- Sources have no dependency on strategies or execution.
- Strategies are deterministic domain logic and perform no I/O.
- An `OrderIntent` is valid by construction; rejected rules are represented
  outside it.
- Exactly one sizing mode is used: share quantity or currency notional.
- Idempotency joins `signal_id` with `template_id`.
- Cancel/replace scope is always `order_group`, never every order on an asset.
- Domain and protocol packages depend only on the Python standard library.
- The existing CBR pipeline remains unchanged until an explicit adapter step.

## Compatibility checkpoint

The existing DTOs in `cbr_trading.pipeline` remain the runtime API for the
tested CBR executor. The new contracts are additive. A later step will add
adapters and migrate one boundary at a time without changing live behavior.
