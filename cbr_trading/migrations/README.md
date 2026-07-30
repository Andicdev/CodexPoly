# Database migrations

Migrations in this directory are additive and are not executed automatically
by the CBR production runner.

`001_add_order_supervision_tables.sql` creates only:

- `resolution_order_groups`;
- `resolution_order_group_orders`;
- `resolution_supervision_events`.

`002_add_order_observations.sql` creates only
`resolution_order_observations`, an append-only audit of exact remote order
state observed before and after cancellation. It does not alter migration 001
or any legacy object.

`003_add_resolution_execution_claims.sql` creates only
`resolution_execution_claims`. It atomically reserves each source-neutral
`scope_id` plus `template_id` after a signal selects an intent and immediately
before the executor can submit an order. It stores the terminal submission and
controlled-test cleanup result. Warm preparation creates no claim, so a
pre-signal process restart is safe; a post-reservation ambiguity remains
fail-closed.

`004_add_earnings_source_tables.sql` creates only:

- `earnings_market_rules`;
- `earnings_source_events`;
- `earnings_fact_candidates`.

These tables hold shadow earnings source configuration, normalized document
metadata, and validated EPS candidates. They do not call a strategy or an
executor, and migration 004 does not seed an armed trading rule.

`005_add_resolution_execution_profiles.sql` creates only
`resolution_execution_profiles`. It stores source-neutral YES/NO preparation
parameters and defaults every profile to `DISABLED`; it does not arm an
executor or submit an order.

`006_add_resolution_profile_templates.sql` creates only
`resolution_profile_templates` and idempotently seeds the `default` row with
YES/NO desired price `0.999`, quantity `50`, and the `0.01 -> 0.001`
single-reprice policy. `ON CONFLICT DO NOTHING` preserves later operator
edits, and existing execution profiles are never changed.

`007_add_trading_account_metadata.sql` creates only
`trading_account_metadata`. It stores public account name, proxy wallet,
venue, signature type, and active status. Encrypted private keys and master
keys remain outside PostgreSQL in the production secret store.

`008_add_mstr_btc_holdings_state.sql` creates only the append-only
`mstr_btc_holdings_state` table. It stores validated or quarantined holdings
observations from official SEC and Strategy ledger sources. A database trigger
rejects updates and deletes. Baseline selection requires both `as_of` and
`observed_at` to precede the requested window boundary, so a late backdated
observation cannot change a baseline that should already have been pinned.

`009_add_mstr_btc_source_audit.sql` creates only:

- `mstr_btc_source_events`;
- `mstr_btc_fact_candidates`;
- `mstr_btc_processing_results`.

All three tables are append-only and protected from updates and deletes by
database triggers. The immutable event is deduplicated independently from its
processing attempts. `ERROR` results may be followed by a later retry, while a
partial unique index permits only one terminal `ACCEPTED`, `NO_MATCH`, or
`QUARANTINED` result per event. Validated facts reference both the source event
and the pre-window holdings state. Migration 009 does not create a resolution
profile, execution claim, intent, or order.

`010_add_source_notification_outbox.sql` creates only
`source_notification_outbox`. Confirmed source events are inserted
idempotently after their canonical fact is durable. A separate worker claims
and sends messages, so Telegram network latency and retries are outside both
the source-ingestion and trading hot paths. The table is mutable only for its
delivery state and does not alter any legacy object.

`011_add_earnings_release_catalog.sql` creates only
`earnings_release_catalog`. It stores reusable, non-secret research about an
earnings date, official schedule evidence, known document formats, candidate
metrics, and tested delivery channels. It is informational and does not arm
polling, create an earnings market rule or execution profile, or submit an
order. A new release receives a new event row, so previous research remains
available for historical comparison.

`012_add_resolution_profile_schedules.sql` adds the source-neutral
`resolution_profile_schedules` lifecycle table and the append-only
`resolution_profile_schedule_events` audit table. Existing execution-profile
columns and statuses are not changed. `AUTO_PREFLIGHT` requests an
authenticated, non-submitting readiness check but cannot enable a profile.
`AUTO_LIVE` additionally requires the global scheduler switch, a fresh
readiness result, an in-window schedule, and an aggregate notional cap.
Lifecycle Telegram messages use the existing durable notification outbox.

`014_add_resolution_run_journal.sql` adds a source-neutral current-summary
table and an append-only timeline table for post-run evaluation. The journal
separates execution, latency, and direction status so an accepted but
unmatched `0.99`/`0.999` order can be classified as a latency miss, a filled
order with the correct direction can be classified as success, and sanitized
source, parser, preparation, submission, supervision, or notification errors
remain queryable for the next reporting cycle. Journal updates are
asynchronous and do not add work to the trading hot path.

`015_set_default_resolution_profile_quantity_100.sql` updates only the
operator-managed `default` template from quantity `50` to `100`. Existing
execution profiles remain unchanged and must be explicitly reviewed before
adopting the larger quantity.

`016_add_earnings_source_telemetry.sql` creates only:

- `earnings_source_processing_telemetry`;
- `earnings_source_transport_observations`.

The processing row records the transport that won processing plus
document-fetch, parse, and fact-persistence stage timestamps. The observation
table independently records every transport that saw the same deduplicated
document, so SEC-API WebSocket, SEC current filings polling, company IR, and
press-wire discovery latency can be compared. First-seen telemetry is inserted
in the same SQL statement as the source event, without another
application/database round trip. Existing rows are retained and represented
as `legacy_unknown`; the original earnings tables are not altered, preserving
compatibility with the previous runtime and its exact schema check.

`017_add_completed_profile_schedule_state.sql` expands only the check
constraints on the additive lifecycle schedule and event tables. It adds the
successful terminal state `COMPLETED` without changing existing rows, state
values, columns, profile definitions, claims, or order supervision records.
Fresh databases receive the same state from migration 012; existing databases
apply migration 017 before starting a completion-aware resolution worker.

`019_add_earnings_release_timing.sql` adds optional research fields that
separate the earliest expected publication from the scheduled point estimate
and conference call. Legacy catalog rows remain valid with all timing fields
null.

`020_add_resolution_timing_contract.sql` adds an optional versioned
earliest-signal boundary to schedules. Existing schedules remain version 0.
New `AUTO_LIVE` inserts/transitions and `activate_at` changes are rejected
unless version 1 proves that activation precedes the earliest plausible
signal by the configured safety lead.

`018_add_observation_only_earnings_facts.sql` expands the existing earnings
fact-status constraint with `OBSERVED` and creates
`earnings_source_race_observations`. `OBSERVED` rows retain parsed official
values and source timing for post-resolution comparison but are excluded from
the existing `VALIDATED` source query, so they cannot authorize trading. The
view derives provider rank, `source_race_lag_ms`, and value agreement without
rewriting historical facts.

The migrations do not alter or drop legacy tables, columns, constraints, or
data.
`SqlAlchemyOrderGroupRepository.migrate()` applies migrations 001 and 002 in
one transaction. `ensure_ready()` independently verifies all required
supervision tables and columns before an `OrderSupervisor` is allowed to use
them.

Migration 003 is owned separately by
`SqlAlchemyResolutionExecutionLedger.migrate()`. The source-neutral live
executor calls only `ensure_ready()` and never applies the migration during
normal startup.

The opt-in supervision runtime calls `ensure_ready()` before the live executor
is prepared. It never calls `migrate()` and cannot create or modify schema
objects during normal runner startup.

There is intentionally no destructive down migration. If the new supervisor
is disabled, the additional tables can remain in place without affecting the
legacy runtime.

## Deployment checkpoint

On 2026-07-24, migrations 001 and 002 were explicitly applied to the
configured primary database outside normal runner startup. The post-migration
check confirmed:

- all four new tables started with zero rows;
- all four required partial/audit indexes were present;
- the expected foreign-key counts were `0`, `1`, `1`, and `2` respectively;
- `SqlAlchemyOrderGroupRepository.ensure_ready()` passed;
- the legacy schema remained at 58 tables and 770 columns before and after the
  migration.

Later on 2026-07-24, migration 003 was explicitly applied through
`python -m scripts.manage_resolution_execution_schema --apply`. Its
before/after checkpoint confirmed:

- `resolution_execution_claims` was newly created with zero rows;
- `SqlAlchemyResolutionExecutionLedger.ensure_ready()` passed;
- the separately counted legacy schema remained at 58 tables and 815 columns
  before and after migration 003.

After the controlled live smoke test, a read-only aggregate audit showed one
`EXECUTED` claim and one claim containing `smoke_cleanup`; no pending or error
claim remained.

Later on 2026-07-24, migration 004 was explicitly applied through
`python -m scripts.manage_earnings_schema --apply --seed-nvts-shadow`. Its
before/after checkpoint confirmed:

- the three earnings tables were newly created;
- one NVTS Q2 2026 rule was saved with source status `SHADOW`;
- both runtime tables started with zero rows;
- `SqlAlchemyEarningsStore.ensure_ready()` passed;
- the separately counted legacy schema remained at 58 tables and 815 columns
  before and after migration 004.

Additional company rules use the same additive tables and can be upserted
without another migration through
`python -m scripts.manage_earnings_schema --seed-checked-in-shadow`.

On 2026-07-26, migration 008 was applied first to staging and then to
production through the fixed stdin-only migration runners. The checked-in
July 20 MSTR baseline was seeded in both environments:

- holdings: `843775` BTC;
- reported as of: July 19, 2026 with date-only precision;
- SEC acceptance: July 20, 2026 at 12:00:16 UTC;
- provider event: `0001193125-26-308369`.

The staging seed was applied twice to prove operational idempotency. A
read-only invariant in each environment confirmed that the baseline selected
strictly before July 21, 2026 at 04:00 UTC is the seeded row, that the
append-only trigger exists, and that no MSTR execution profile or claim was
created.
