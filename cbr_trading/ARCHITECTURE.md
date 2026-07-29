# Resolution trading architecture

This document records the contracts accepted for the new project. The legacy
repository at `C:\polymarket-bot` is a read-only reference and is not modified.

## Governing priorities

Resolution trading is optimized for two ordered goals:

1. **Correct resolution.** A document may become a tradable signal only when
   its issuer, event scope, period, metric, value, and publication identity
   are unambiguous. Unsupported or conflicting evidence is quarantined and
   fails closed.
2. **Extreme end-to-end latency.** After validation, every avoidable serial
   operation is removed from the path between first official evidence and the
   exchange submission.

Correctness is therefore a hard gate, not a latency trade-off. Once multiple
implementations satisfy the same parsing and safety contract, the fastest
measured end-to-end design is preferred.

These priorities imply several architectural defaults:

- official delivery routes for one event race independently; a slow or failed
  route cannot delay another route;
- WebSocket feeds may stay connected, while HTTP polling is profile-gated and
  runs only inside a reviewed preparation window;
- the first valid provider wins, but all providers emit the same canonical
  fact and stable event scope;
- both outcome alternatives and every static dependency are prepared before
  publication;
- all markets resolved by one publication are evaluated and submitted as one
  batch rather than through serial per-profile executors;
- only parsing, deterministic strategy selection, persistent idempotency
  claims, and exchange submission belong on the post-signal hot path;
- notifications, enrichment, nonessential journaling, and lifecycle work run
  after submission or asynchronously;
- every source route and execution stage records enough monotonic timing data
  to locate latency rather than infer it from final order timestamps.

The implementation and review checklist for these rules is
`cbr_trading/SOURCE_DESIGN_CHECKLIST.md`.

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
   Company earnings keep upstream delivery channels internal: SEC WebSocket
   or company IR metadata becomes an `EarningsDocumentCandidate`, a
   company parser produces an `EarningsFactCandidate`, and
   `EarningsResolutionSource` emits one canonical signal under a stable
   fiscal-period scope such as `earnings:NVTS:2026Q2`. Providers are evidence
   channels, not separate trading sources. The earnings package currently
   runs only in shadow mode and has no strategy or execution dependency.
2. A `Strategy` exposes all static `OrderTemplate` alternatives before the
   event. After a signal arrives, it selects templates and binds them into
   concrete, idempotent `OrderIntent` objects.
3. A `PreparedExecutor` prepares templates before polling. A stable
   `PreparationContext` binds that work to the expected source publication.
   Preparation may resolve accounts, assets, tick metadata, neg-risk,
   and signatures. Execution accepts only selected intents whose signal and
   parameters match that prepared scope, then atomically reserves persistent
   idempotency claims immediately before the first submission call.
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
- `resolution_order_observations` stores immutable remote snapshots,
  including price, original, matched, and remaining quantity. The normal
  replace-first path records `PRE_CANCEL`; legacy/recovery rows may also use
  `POST_CANCEL` and `RECONCILE`.

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
3. Before replacement, the gateway reads every exact `live_order_id`.
   The supervisor verifies account-scoped market ownership, side, and original
   sizing against the persisted group.
4. Orders already `FILLED` need no replacement. The remaining replacement
   size comes from this first remote snapshot: quantity sizing preserves
   currently unfilled shares and notional sizing preserves their old-order
   notional. A full fill completes the group without a new order.
5. The desired price is aligned to the target tick: BUY rounds down and SELL
   rounds up. The target-tick order is submitted before any cancellation so
   exchange cancellation consistency cannot block the latency-sensitive
   placement.
6. Only the exact remotely `OPEN` source IDs are then sent to best-effort
   batch cancellation. The cancellation acknowledgement is validated, but
   there is no post-cancel status read or wait for a terminal state. A partial
   cancellation fails the claim only after the already-known replacement ID
   has been retained for reconciliation.
7. Successful completion closes filled and replaced source orders, inserts
   the new generation as `LIVE`, and completes the event in one transaction.
   If cancellation or state persistence fails after placement, known
   replacement orders are recorded as `UNKNOWN` so recovery cannot submit a
   blind duplicate.

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

The complete path is covered by
`tests/test_resolution_order_lifecycle_integration.py`. It composes the real
CBR source, strategy, coordinator, warm adapter, supervised executor,
persistent supervisor, tick detector, and market channel. With only external
I/O boundaries replaced by stateful test doubles, it proves:

1. desired BUY price `0.999` is prepared and submitted at `0.99` on tick
   `0.01`;
2. the submitted order ID is registered as one owned order group;
3. a real `0.999` book level proves tick `0.001` even without an explicit
   tick-change event;
4. only the owned initial order is cancelled;
5. the replacement is submitted at `0.999`, becomes the group's live order
   with `reprice_count=1`, and a repeated book observation does not trigger a
   second replacement.

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
- the additive supervisor migrations remain explicit and are never applied by
  the runner; migrations 001 and 002 were applied separately to the configured
  primary database on 2026-07-24, after which `ensure_ready()` passed;
- the official supervision gateway, market-channel adapter, strict book-level
  inference, source-neutral detector, active-watch loader, and recovery loop
  are composed behind the disabled-by-default supervision gate;
- no real supervision cancellation or replacement has been made by this
  implementation work.

## Source-neutral fixed-outcome preflight

The first non-CBR rule path is additive:

- `SqlAlchemyRuleRepository.load_active_rule()` loads one active rule by ID
  without a CBR ticker, metric, or execution-path filter;
- `FixedOutcomeStrategy` turns an exact source/subject/metric/value match into
  one configured BUY template and never prepares the opposite outcome;
- `ManualResolutionSource` emits an explicit controlled signal once;
- `PolymarketPreflightPreparedExecutor` authenticates, refreshes the book,
  checks balance and safety caps, and locally pre-signs arbitrary universal
  templates without reserving or submitting an order;
- `python -m cbr_trading.resolution_live --rule-id <id>` composes these pieces
  through `ResolutionTradingCoordinator` and requires a final `DRY_RUN`.

This preflight does not reuse `CbrWarmPreparedExecutorAdapter`: that adapter
still validates the CBR source scope, prepares both binary outcomes, and uses
the legacy CBR execution ledger. Source-neutral idempotency and real
submission remain a separate checkpoint.

## Persisted-fact hosted composition

The earnings deployment keeps transport and execution in separate services:

```text
SEC source service
    -> VALIDATED earnings_fact_candidates
    -> hosted resolution service
    -> EarningsResolutionSource
    -> ResolutionSignal
    -> NumericThresholdStrategy
    -> one OrderIntent
    -> PreparedExecutor
```

`resolution_execution_profiles` is additive and source-neutral. Each enabled
row binds one stable resolution scope to an account and condition, defines
separate YES/NO prices, quantity, lifecycle policy, and a hard preparation
window. Both templates must prepare successfully before facts are polled. A
condition mismatch with the earnings source rule fails before authentication
or execution.

`resolution_profile_templates` is a separate additive configuration table.
The `default` row is copied when an execution profile is created or updated;
editing it never mutates existing profiles. Per-profile overrides remain
available for exceptional markets. The seeded default uses desired price
`0.999` for either outcome, share quantity `100`, and the `0.01 -> 0.001`
single-reprice policy.

`resolution_profile_schedules` is another additive layer and never replaces
the execution profile. It controls when an already reviewed profile may
become eligible:

```text
Schedule -> LifecycleController -> profile status
                                  -> lifecycle audit
                                  -> Telegram outbox
```

`AUTO_PREFLIGHT` requests a separate authenticated readiness worker which
loads a disabled profile, prepares and pre-signs both outcomes, records only
non-secret aggregate evidence, and closes the executor without calling
`execute()`. A failed attempt remains `PREFLIGHTING` and is retried on a
bounded lease until the scheduler's activation grace ends; the retry audit
stores a classified non-secret error code without sending repeated Telegram
messages. This prevents one transient market/authentication response from
permanently dropping an otherwise valid profile. A successful check moves the
schedule to `READY` but leaves the profile `DISABLED`. `AUTO_LIVE` additionally
requires a fresh readiness
result, the global automatic-live switch, an active window, and an aggregate
worst-selected-outcome notional cap before an atomic transition to
`ENABLED`. After a matching signal has traversed strategy and executor, the
hosted worker atomically moves the schedule from `ACTIVE` to `COMPLETED` and
returns the profile to `DISABLED`. This transition happens after submission
and never cancels an already submitted order. Terminal source-contract,
strategy, or execution failures instead move the schedule to `BLOCKED` with a
safe reason code. An unresolved window ends as `EXPIRED`. All transitions are
append-only audited; notification delivery remains outside the trading hot
path.

Earnings schedules are grouped into independent `PRE_MARKET` and
`POST_MARKET` live blocks through the schedule metadata keys `live_block` and
`block_id`. A block is a lifecycle, preparation-capacity, observability, and
risk boundary, while the same universal resolution worker and executor may
serve both sessions. Only one reviewed earnings block is armed at a time:
starting a pre-market block does not implicitly arm the post-market block,
and switching sessions requires a separate guarded production transition.
See `deploy/lightsail/LIVE_MARKET_BLOCKS.md`.

The hosted service defaults to `shadow`, where the complete decision path
ends at a non-submitting executor. `preflight` authenticates and pre-signs
both alternatives without creating execution claims. `live` uses
`PolymarketPreparedExecutor`; a repricing profile additionally requires the
persistent supervisor and market channel before preparation.

Tick repricing keeps submit-first latency for a fresh tick change. If the
source order has already been live for more than five seconds, the tick event
is no longer treated as hot: the supervisor first inspects the exact owned
orders, skips replacement after a complete fill, and sizes a replacement only
to the observed remainder after a partial fill. An unavailable stale-order
inspection fails closed. This prevents a delayed tick signal from duplicating
an order that filled minutes earlier without adding a lookup to the immediate
submit-first path.

Only `VALIDATED` official facts enter the source. Facts for all scopes are
loaded in one polling snapshot, then each prepared event coordinator consumes
only its own scope. Warm preparation does not create a claim, so a process can
restart safely before a signal. After a matching signal selects an intent, the
executor atomically claims every prepared alternative immediately before it
posts the selected pre-signed order. The unselected alternative is marked
`EXPIRED`, while the selected claim stores the terminal submission result. A
duplicate worker loses the claim race and cannot call the order endpoint. If
the process stops before a signal, there is no claim to clean up. A crash
after reservation remains deliberately fail-closed because submission may be
ambiguous.
