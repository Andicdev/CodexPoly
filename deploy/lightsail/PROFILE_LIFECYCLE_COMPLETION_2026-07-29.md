# Profile lifecycle completion checkpoint

## Scope

This checkpoint closes the gap between successful resolution execution and
profile eligibility. It changes source-neutral lifecycle code, schema
constraints, notifications, and hosted-worker integration locally. No
production migration, deployment, profile transition, order mutation, or
secret operation was performed.

The production database was inspected through
`checks/diagnose_july_29_profile_completion_gap.sql`, using the guarded
read-only migration runner. The guard confirmed that the July 29 block still
contained at least one schedule in `ACTIVE` or `BLOCKED` despite an existing
`EXECUTED` resolution claim. No row data was returned.

## Correct lifecycle

```text
PENDING
  -> PREFLIGHTING
  -> READY
  -> ACTIVE
       -> COMPLETED  successful signal/strategy/executor path
       -> BLOCKED    terminal preparation, contract, strategy, or execution error
       -> EXPIRED    no resolution before the window closes
```

`COMPLETED` is distinct from `EXPIRED`: the former proves that the universal
resolution path consumed a signal, while the latter means the eligibility
window ended without that successful transition.

## Runtime behavior

Earnings, MSTR BTC, and FED hosted workers now call the same completion helper
after `CoordinationStatus.COMPLETED`. The lifecycle store atomically:

1. locks the matching `AUTO_LIVE` / `ACTIVE` schedule and enabled profile;
2. disables the execution profile for new signals;
3. changes the schedule to `COMPLETED`;
4. appends `RESOLUTION_EXECUTION_COMPLETED`;
5. records that existing submitted orders were left unchanged.

The completion call runs after executor submission. A transient lifecycle
persistence failure is sanitized, logged by exception type only, and retried
from the in-memory coordinator's completed state without repeating strategy or
execution.

Permanent coordinator failures use specific safe lifecycle reasons:

- `live_source_contract_failed`;
- `live_strategy_evaluation_failed`;
- `live_execution_failed`;
- existing preparation failures remain
  `live_profile_preparation_failed`.

A transient failure while persisting `BLOCKED` is also sanitized and retried
from the coordinator's terminal in-memory state. Strategy and execution are
not repeated during that retry.

## Compatibility

Migration `017_add_completed_profile_schedule_state.sql` expands only the
allowed values of the two additive lifecycle tables. Existing rows, fields,
states, event history, execution claims, profiles, and order groups remain
unchanged. Migration 012 also includes `COMPLETED` for clean installations.

Historical manually completed schedules stored as `MANUAL` / `EXPIRED` remain
valid. The new expiry query excludes `COMPLETED`, so a successful terminal
state cannot later be overwritten by ordinary window expiry.

## Deployment boundary

The next stage must apply migration 017 before deploying the new image. The
new worker intentionally fails its lifecycle schema readiness check if the
database constraints do not yet accept `COMPLETED`.
