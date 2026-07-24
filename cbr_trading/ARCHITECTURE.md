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

### Market tick observation

`TickSizeChangeDetector` is the source-neutral boundary between market data
and `OrderSupervisor`. Each configured `TickSizeWatch` names exactly one
policy-backed transition for an asset. It does not guess arbitrary tick sizes.
An observation is actionable only when it matches that configured transition.

The detector uses one stable event ID for an `asset + old_tick + new_tick`
transition regardless of which transport observed it. It updates its in-memory
current tick only after the supervisor call returns successfully. Therefore a
WebSocket event and a later order-book snapshot cannot initiate the same
transition twice, while a transient supervisor exception remains retryable.
The observation source is stored in the existing supervision-event JSON
payload; no schema change is required.

`PolymarketMarketChannel` subscribes only to the watched outcome token IDs
through the official public SDK. The SDK owns socket heartbeat, reconnect, and
subscription-state resend. Synchronous supervisor work runs outside the async
event loop so cancellation and remote inspection cannot block those socket
tasks. Three forms of WebSocket evidence are accepted:

- an explicit `tick_size_change` event whose reported old tick, when present,
  matches the detector's current tick;
- the explicit `tick_size` field on a full `book` event;
- a live `book` or `price_change` level whose price is invalid on the current
  grid but valid on the configured finer grid.

A zero-size price change is a removed level and is not evidence. Prices that
remain valid on the old grid are also not evidence of the old tick, because a
finer market can still contain such prices. This intentionally supports the
case where the explicit tick event is missed but a real `0.999` bid or ask is
observed while the configured transition is `0.01 -> 0.001`.

The same adapter exposes `observation_for_book(..., source=PERIODIC_BOOK)` for
a future periodic snapshot check. That fallback will feed the same detector
instead of creating a second repricing path.

### Supervision runtime composition

`SupervisedPreparedExecutor` decorates any `PreparedExecutor`. Immediately
after an attempted result returns known orders and an `ExecutionHandle`, it
registers only `RepriceOnTickChange` ownership with `OrderSupervisor`.
`KeepOpenPolicy` results do not create permanent inactive supervision rows.
If registration fails after submission, the known order result becomes
`AMBIGUOUS` and retains its handle and order IDs; the failure is never reported
as an ordinary successful submission.

`SqlAlchemyOrderGroupRepository.load_active_tick_size_watches()` derives the
subscription set only from active persisted groups whose reprice budget is not
exhausted. Multiple groups may share one identical asset transition, but
conflicting transitions for the same asset fail closed.

`OrderSupervisionRuntime` starts before executor preparation and remains active
while the source is being polled. It:

1. runs bounded reconciliation on its configured interval;
2. refreshes active watches and restarts the exact SDK subscription only when
   the watched set changes or the channel ends;
3. picks up a newly registered order group on the next refresh, after which a
   fresh full-book subscription can recover a missed tick event;
4. keeps the runner alive after source completion while an active or
   recoverable persisted group exists;
5. closes the market channel, gateway, repository, and background thread when
   persistent work becomes idle or shutdown is requested.

The CBR runner composes this path only when
`RESOLUTION_SUPERVISION_ENABLED=1` and `CBR_DRY_RUN=0`. A live rule containing
`RepriceOnTickChange` is rejected before order preparation when the gate is
off. When the gate is on, schema readiness is checked before the live executor
can reserve or submit anything. Runtime startup failure also swaps in the
non-submitting executor before preparation.

The gate never applies migrations. Migrations 001 and 002 remain explicit,
forward-only deployment actions.

The warm CBR bridge keeps the strategy's `desired_price` separate from the
initially signed `effective_price`. For `reprice_on_tick_change`, preparation
accepts only the configured old or new tick and derives the effective price
with the same side-aware tick normalization used by the supervisor. Thus a BUY
with desired price `0.999` is signed at `0.99` while the market is on tick
`0.01`, but its persisted order-group handle retains `0.999` for replacement
when tick `0.001` becomes active. `keep_open` prices are never normalized and
must still align exactly to the current tick. A submitted order is registered
for tick supervision only when its effective price still differs from its
desired price, so an order prepared after the finer tick is already active is
not cancelled and replaced with the same price.

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
- A book price can confirm only a preconfigured finer tick. Aligned prices
  cannot prove that the old tick is still active, and market data never
  invents an unconfigured transition.
- Tick observation state is committed only after supervisor dispatch returns;
  transport-specific duplicate observations share one transition event ID.
- A live repricing policy cannot submit through the CBR runner unless
  supervision is enabled, its schema is ready, and its runtime starts before
  executor preparation.
- Known submitted repricing orders are persisted synchronously before their
  result is reported as `SUBMITTED`; registration failure is `AMBIGUOUS`.

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
- the additive supervisor migrations remain explicit and have not been applied
  by the runner;
- the official supervision gateway, market-channel adapter, strict book-level
  inference, source-neutral detector, active-watch loader, and recovery loop
  are composed behind the disabled-by-default supervision gate;
- no real supervision cancellation or replacement has been made by this
  implementation work.
