# VIRT release-window incident and timing contract — 2026-07-30

## What happened

The VIRT schedule used:

- authenticated preflight at `10:00 UTC`;
- activation at `10:30 UTC`;
- issuer webcast at `11:00 UTC`.

The SEC document fetch won at `10:06:00.234 UTC`, and the canonical VIRT fact
was persisted at `10:06:00.590 UTC` with normalized adjusted EPS `1.82`.
The schedule was still `READY` and its execution profile was `DISABLED`, so
the first signal did not submit an order. The scheduler activated VIRT at
`10:30 UTC`; retaining the fact for later processing was accepted by the
operator.

The root cause was schedule research that treated the issuer call as the
primary timing anchor. A call/webcast is a later presentation event and is
not a safe lower bound for publication.

## Immediate MA protection

MA was already authorized for `AUTO_LIVE`, but its original activation was
`11:00 UTC`. Because Mastercard confirmed only its `13:00 UTC` call and did
not give an exact publication time, the schedule was moved earlier without
changing the profile, account, prices, quantity, or caps.

The first correction crossed its fixed activation time before the scheduler
could request preflight. The scheduler correctly failed closed with
`preflight_not_requested`; there was no fact, claim, or order. A guarded
recovery reset only that expected state, requested preflight immediately, and
set activation three minutes later:

- authenticated preflight ready: `10:23:43 UTC`;
- schedule/profile activated: `10:26:41 UTC`;
- limits unchanged: `100 / 100 / 1000`.

## Permanent timing contract

Additive migrations 019 and 020 introduce:

- catalog `earliest_expected_release_at`, kept separate from
  `scheduled_release_at` and `conference_call_at`;
- timing basis, confidence, evidence URL, and safety lead;
- schedule `earliest_signal_at`, safety lead, evidence, and
  `timing_contract_version`;
- the invariant
  `activate_at <= earliest_signal_at - activation_safety_lead`;
- a PostgreSQL trigger rejecting new `AUTO_LIVE` inserts/transitions and
  activation-time changes without version 1.

Legacy schedules remain version 0 and readable. The Python catalog and
lifecycle contracts enforce the same boundary before persistence.

Both migrations and the read-only schema verifier passed in staging. A
transactional staging probe proved that the trigger rejects unsafe legacy-to-
`AUTO_LIVE` transitions and rolls back all test writes.

Production migration/image rollout is intentionally deferred until the active
July 30 earnings block ends. The current runtime performs exact schema-column
checks, so applying the additive columns without the matching immutable image
would make an unexpected worker restart fail readiness.
