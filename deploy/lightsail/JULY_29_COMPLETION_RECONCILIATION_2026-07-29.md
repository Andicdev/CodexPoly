# July 29 historical completion reconciliation

## Scope

Stage 6 reconciled only the July 29 pre-market profiles that already had an
accepted terminal `EXECUTED` claim:

- `earnings-sofi-2026q2`;
- `earnings-pg-2026q4`;
- `earnings-hum-2026q2`;
- `earnings-iart-2026q2`;
- `earnings-grmn-2026q2`.

The guarded read-only diagnostic proved that each exact scope had one accepted
and attempted `EXECUTED` claim with one order ID plus its unselected
unattempted `EXPIRED` claim. No other profile in the July 29 pre-market block
had an `EXECUTED` claim.

## Migration

Application commit `b1a8c8b` introduced migration
`021_reconcile_july_29_executed_profiles.sql` and its exact diagnostic and
post-check.

The migration:

- locks only the five exact schedule/profile rows;
- accepts only their previously observed `ACTIVE` or `BLOCKED` lifecycle
  states and the exact terminal claim shape;
- writes one deterministic `RESOLUTION_EXECUTION_COMPLETED` audit event per
  schedule with reason `historical_executed_claim_reconciled`;
- marks the schedules `COMPLETED`, clears their lifecycle error, and disables
  their profiles;
- explicitly marks the event and schedule metadata as a historical
  reconciliation with existing orders left unchanged.

It does not update or delete orders, execution claims, source facts, earnings
rules, release catalog rows, or run-journal rows. It cannot submit, replace,
or cancel an order.

## Production evidence

The production migration completed successfully. The exact read-only
post-check then confirmed:

- exactly five reconciled schedules are `COMPLETED`;
- all five profiles are `DISABLED`;
- all five schedules have exactly one matching completion audit event;
- the original five accepted `EXECUTED` and five unselected `EXPIRED` claims
  remain unchanged;
- no `ACTIVE` or `BLOCKED` July 29 schedule still has an `EXECUTED` claim;
- no unexpected July 29 schedule was marked `COMPLETED`.

The same migration was applied a second time to exercise its production
idempotency. The exact post-check still passed with the same five rows and
events.

The first generic lifecycle post-check rejected the new rows because its
legacy assertion recognized only a live `ACTIVE -> COMPLETED` transition with
reason `resolution_execution_completed`. The production data had already
passed the stricter exact reconciliation check. The generic check was
therefore extended to recognize two explicit and non-overlapping paths:

1. normal live completion from `ACTIVE`;
2. historical completion from `ACTIVE` or `BLOCKED`, but only with the
   historical reason and both audit metadata guards.

The corrected generic invariant and the guarded live-runtime heartbeat check
both passed.

## Runtime and notifications

No worker was recreated for this database-only reconciliation. All five
production workers remained on immutable image
`codexpoly@sha256:c4240d8500b1b477b7be5d1878c43add945895cb84643d3c7edff42647cc2146`,
running with zero restarts.

Sanitized logs showed five additional lifecycle notifications delivered on
their first attempt. The notification heartbeat advanced from 6 claimed,
6 sent, and 0 failed to 11 claimed, 11 sent, and 0 failed. The scheduler
reported the same notification total with automatic live scheduling enabled
and no new activation, block, or expiry error.

No resolution signal was processed and no order was submitted, replaced, or
cancelled by this stage.

## Remaining boundary

Only profiles with proven terminal execution evidence were reconciled. The
other July 29 pre-market profiles were intentionally not marked successful.
Their source/parser and execution timelines remain available for the separate
latency and outcome audit.
