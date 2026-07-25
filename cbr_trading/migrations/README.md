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
`scope_id` plus `template_id` before polling can submit an order, and stores
the terminal submission and controlled-test cleanup result.

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
