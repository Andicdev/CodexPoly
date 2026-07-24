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

## Persistent order ownership

The supervisor persistence boundary is additive and source-neutral:

- `resolution_order_groups` stores immutable intent ownership, lifecycle
  policy, optimistic `revision`, and the current group state;
- `resolution_order_group_orders` stores every initial and replacement order
  owned by a group, including its generation and lifecycle state;
- `resolution_supervision_events` provides per-group event idempotency and
  records atomic tick-change claims;
- `resolution_order_observations` stores immutable `PRE_CANCEL` and
  `POST_CANCEL` remote snapshots, including price, original, matched, and
  remaining quantity.

An `ExecutionHandle` carries the optional signal/template/strategy and order
parameters needed to persist a replaceable order without re-reading a
source-specific rule. Repricing registration requires side, desired price,
and exactly one sizing mode.

The migrations are intentionally forward-only and additive. They use only
`CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`; they do not
alter or drop any legacy table, column, constraint, or data. Migration 002
only adds the observation table and leaves migration 001 unchanged. The
production runner does not apply migrations automatically. Migration and
readiness verification are explicit repository operations.

## Persistent supervisor lifecycle

`PersistentOrderSupervisor` is the source-neutral cancel/replace service:

1. It loads only active groups for the asset named by a tick-size event.
2. The repository atomically claims each matching group and rejects duplicate
   or competing processing by event ID and optimistic revision.
3. Before cancellation, the gateway reads every exact `live_order_id`.
   The supervisor verifies account-scoped market ownership, side, and original
   sizing against the persisted group.
4. Orders already `FILLED` need no cancellation. Only remotely `OPEN` IDs are
   sent to exact batch cancellation; remotely `CANCELLED` IDs remain inside
   the same owned group. A partial cancellation is a failure and no
   replacement is submitted.
5. After successful cancellation, every formerly open order is read again.
   Replacement is forbidden unless the final state is `CANCELLED` or
   `FILLED`. This second snapshot closes the race where another fill arrives
   while cancellation is in flight.
6. The remaining replacement size comes from the final remote state. Quantity
   sizing preserves unfilled shares. Notional sizing preserves only the
   unfilled old-order notional. A full fill completes the group without a new
   order.
7. The desired price is aligned to the target tick: BUY rounds down and SELL
   rounds up. Successful completion stores both snapshots, closes filled and
   replaced orders, inserts the new generation as `LIVE`, and completes the
   event in one transaction. If state persistence fails after placement,
   known replacement orders are recorded as `UNKNOWN`.

This checkpoint defines and tests the supervisor and its order-gateway
contract. `PolymarketSupervisionOrderGateway` is the first live implementation
of that contract. It uses the official `SecureClient` and:

- authenticates the persisted account and verifies its wallet and signature
  type before any cancellation or placement;
- requires the existing live-trading switch, allowed-account setting, and
  account master key;
- calls only `cancel_orders(order_ids=...)` with the exact group-owned IDs;
  it never calls account-wide or market-wide cancellation;
- calls `get_order(order_id=...)` separately for each exact owned order and
  normalizes SDK `original_size`, `size_matched`, price, and status into a
  source-neutral snapshot;
- preserves partial cancellation results so confirmed external effects can be
  persisted before the group fails;
- refreshes the order book and verifies condition, asset, target tick,
  minimum size, BUY/SELL post-only crossing, and all configured quantity and
  notional caps before submitting one GTC replacement;
- supports either persisted share quantity or currency notional sizing and
  normalizes accepted and rejected SDK responses without exposing secrets.

### Background reconciliation

`PersistentOrderSupervisor.reconcile()` now performs a bounded recovery scan
without submitting or cancelling any order:

1. It loads `FAILED` and stale `REPRICING` groups older than the configured
   recovery delay. Groups already marked for manual review are excluded.
2. A new `order_reconciliation` event claims the exact group revision. When
   the candidate was a stale `REPRICING` operation, its old `CLAIMED` event is
   atomically marked `FAILED` as superseded.
3. The gateway reads only order IDs already owned by the group. The resulting
   `RECONCILE` observations and local order states are persisted
   transactionally.
4. Automatic recovery is allowed only when a replacement order ID was already
   persisted, every source order is terminal, and the replacement price and
   original quantity exactly match the final source remainder. The known
   replacement is then promoted from `UNKNOWN` to `LIVE`, `FILLED`, or
   `CANCELLED`, and the interrupted reprice count is completed.
5. A missing replacement ID, simultaneous open source and replacement orders,
   or a sizing mismatch is quarantined with
   `metadata.reconciliation_manual_review = true`. The scanner will not touch
   that group again automatically. Transient lookup or unknown remote states
   remain retryable after the recovery delay.

This distinction is intentional. A process can die after an exchange accepts
an order but before its ID reaches the database. Without a persisted ID, an
automatic replacement could duplicate exposure, so recovery fails closed.

The live adapter and reconciliation scan are not composed into the production
runner yet. This stage also does not connect a real market-channel listener,
apply either migration to a real database, or enable supervision.

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
- A tick event is claimed by changing one group from `ACTIVE` to `REPRICING`
  under an optimistic revision. Duplicate or competing events cannot acquire
  the same group.
- Persistent cancellation scope is the exact order IDs recorded for one
  `order_group`; legacy asset-wide ownership is never inferred.
- A replacement is never submitted from a pre-cancel snapshot alone. A
  post-cancel terminal snapshot is mandatory for every order that was open.

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
- the additive supervisor migration and persistent supervisor are defined but
  are not yet applied or consumed by the production runner;
- the official Polymarket supervision gateway is implemented and tested with
  fake authenticated clients, but is not instantiated by the runner and has
  made no real cancellation or placement.
