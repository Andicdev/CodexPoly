# Profile lifecycle scheduler checkpoint

Date: 2026-07-27

## Implemented boundary

The source-neutral execution profile remains the definition of what may be
traded. Additive migration 012 introduces a separate time lifecycle:

```text
resolution_profile_schedules
    -> profile-scheduler-worker (database only)
    -> resolution_profile_schedule_events
    -> source_notification_outbox
    -> notification-worker
```

The production trading overlay additionally defines
`profile-readiness-worker`. It claims a due preflight request, loads the
disabled execution profile, authenticates and pre-signs both outcomes through
`PolymarketPreflightPreparedExecutor`, persists only aggregate non-secret
readiness evidence, and closes the executor. It never calls `execute()` and
never submits an order.

## Fail-closed defaults

- existing profile columns and legacy objects are not altered;
- new schedules default to `MANUAL` and `PENDING`;
- the production scheduler has no trading secrets;
- the name-only manifest grants the scheduler only
  `DATABASE_APP_PASSWORD`, while the readiness worker receives exactly the
  existing database, master-key, and encrypted-key file names;
- `PROFILE_SCHEDULER_AUTO_LIVE_ENABLED=0`;
- the July schedule seed uses `AUTO_PREFLIGHT` only;
- a successful scheduled preflight moves the schedule to `READY` while the
  execution profile remains `DISABLED`;
- a missing or failed authenticated preflight moves the schedule to
  `BLOCKED`;
- schedule expiry leaves the execution profile `DISABLED`;
- lifecycle messages are delivered asynchronously through the existing
  Telegram outbox.

`AUTO_LIVE` must remain disabled during this checkpoint. A later stage must
add dynamic profile refresh to the long-running live resolution service,
approve the aggregate batch risk, and receive explicit production-live
authorization before the global switch may change.

## Scheduled batch

Seed `009_schedule_july_28_auto_preflight.sql` contains 15 exact profiles:

- July 28 pre-market: PYPL, UPS, HLT, IVZ, KO, RCL, BA, JBLU, SPGI;
- July 28 post-market: CZR, CSGP, V, F, NXPI;
- July 29 post-market: SBUX.

Each preflight is requested 15 minutes before the profile's existing
`prepare_from`. The seed refuses to finish unless all 15 schedules exist in
`AUTO_PREFLIGHT` and all 15 execution profiles remain `DISABLED`.

## Telegram lifecycle messages

The outbox receives idempotent messages for:

- authenticated preflight requested;
- authenticated preflight ready;
- preflight or activation blocked, including a safe reason code;
- profile enabled (future `AUTO_LIVE` only);
- window expired.

The profile-enabled message says only that status is `ENABLED` and that a
matching source signal may now be accepted. It does not claim that an order
was placed. Every message includes the Polymarket market link.

## Verification

Local verification completed:

```text
python scripts/check_no_secrets.py
python -m unittest discover -s tests -q
```

Result:

```text
Secret scan passed
604 tests passed
1 test skipped
```

No database migration, production Compose change, schedule seed, authenticated
preflight, profile activation, or Telegram message was applied as part of
this code checkpoint.
