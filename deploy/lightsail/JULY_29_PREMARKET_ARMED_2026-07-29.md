# July 29 PRE_MARKET production checkpoint

Date: 2026-07-29

## Scope

Only the following reviewed PRE_MARKET profiles were added and armed:

- SOFI 2026 Q2
- PG 2026 Q4
- HUM 2026 Q2
- WING 2026 Q2
- ARCC 2026 Q2
- IART 2026 Q2
- GRMN 2026 Q2
- CBRE 2026 Q2
- PAG 2026 Q2

The July 29 POST_MARKET profiles, WWD carryover, and the existing SBUX
schedule were not changed.

## Production sequence

1. A normal production PostgreSQL backup completed before the first database
   change.
2. `020_bootstrap_july_29_premarket_profiles.sql` added only SOFI, PG, and HUM
   in `DISABLED` / `AUTO_PREFLIGHT` state.
3. `018_add_july_29_premarket_profiles.sql` added the remaining six profiles
   and the reviewed public-source policies.
4. `verify_july_29_premarket_profiles.sql` passed in a read-only transaction.
5. `018_arm_july_29_premarket_live_block.sql` changed only the nine target
   schedules to `AUTO_LIVE`. It did not enable execution profiles.
6. `verify_july_29_premarket_auto_live_armed.sql` passed in a read-only
   transaction.

The reviewed aggregate notional is `899.1`, below the configured `1000` cap.
All nine profiles use quantity `100` and desired prices `0.999 / 0.999`.
There were no validated facts, execution claims, or active order groups for
the target scopes at arming time.

## Runtime checkpoint

At the arming checkpoint:

- `earnings-worker`, `resolution-worker`, `profile-scheduler-worker`, and
  `profile-readiness-worker` were running;
- the hosted resolution heartbeat was fresh, in live mode, with supervision
  and trading enabled;
- the lifecycle scheduler reported `auto_live=True`, `blocked=0`, and
  `expired=0`;
- the readiness worker reported `blocked=0`;
- all nine execution profiles remained `DISABLED`.

## Scheduled transition

The scheduler is expected to request authenticated preflight at
`2026-07-29 08:45:00 UTC`. Readiness is intentionally not created earlier
because its TTL is 30 minutes. A profile may transition from `READY` to
`ACTIVE` at `2026-07-29 09:00:00 UTC` only while its readiness evidence and
the fully-live resolution heartbeat remain fresh.

Any failed authenticated preflight or failed activation guard leaves the
affected profile non-live and records a lifecycle event for Telegram
delivery.
