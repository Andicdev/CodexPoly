# Profile completion audit semantics

Status: production verifier corrected; no data backfill required.

## Read-only diagnosis

The generic completion verifier initially assumed that every `COMPLETED`
schedule must contain a `RESOLUTION_EXECUTION_COMPLETED` event. A
purpose-built read-only diagnostic returned exactly two exceptions:

| Profile | Completion reason | Validated fact | Execution claims | Active order groups |
| --- | --- | ---: | ---: | ---: |
| `earnings-hood-2026q2` | `official_result_observed_execution_missing` | 1 | 0 | 0 |
| `earnings-msft-2026q4` | `official_result_parser_quarantined` | 0 | 0 | 0 |

Both schedules were already `COMPLETED`, both profiles were `DISABLED`, and
both had exactly one `POST_EVENT_RECONCILIATION_COMPLETED` event:

- HOOD moved from `BLOCKED` after an official fact was observed but the live
  execution path had never created a claim;
- MSFT moved from `ACTIVE` after its official source document was
  quarantined, with no validated fact and no execution claim.

Writing `RESOLUTION_EXECUTION_COMPLETED` for either schedule would therefore
create false trading evidence. No schedule, profile, event, claim, fact,
order group, or run-journal row was inserted or updated.

## Verifier correction

`verify_profile_completion_runtime_invariants.sql` now accepts exactly one of
two terminal audit classes:

1. `RESOLUTION_EXECUTION_COMPLETED`, with the existing live or historical
   executed-claim evidence;
2. `POST_EVENT_RECONCILIATION_COMPLETED`, restricted to the two reviewed
   reason codes and guarded by:
   - matching schedule completion reason;
   - `investigation_required=true`;
   - no execution claim;
   - no order group;
   - `existing_orders_left_unchanged=true`;
   - a validated fact for the HOOD reason; or
   - no validated fact plus a quarantined source event for the MSFT reason.

The verifier also requires one total terminal completion audit event per
schedule across both event classes.

## Production evidence

The corrected verifier passed through the fixed staging runner and the
production migration runner in read-only transactions. The independent fresh
live-heartbeat and safe-idle guards also passed. Production workers were not
restarted, no profile was enabled, and no order was prepared or submitted.
