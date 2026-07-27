# Profile lifecycle AUTO_PREFLIGHT production checkpoint

Date: 2026-07-27

## Reviewed release

- Runtime source commit: `94a3645`.
- Clean source archive SHA256:
  `45904cb0eb3cf2770b873218ae3e7712f40a93a22bcb495a873a2f1d5aa0f2f7`.
- Image archive SHA256:
  `731ed866de61317924bb2e66adee9725633e8f5506372da1cadd2cdf76a292cb`.
- Immutable image:
  `codexpoly@sha256:fe0aa4d093c666a01e56a7acbf287a30ded2c7bb90ae84046e14cdd2e6998ecc`.

The image was built from a clean `git archive` in the rootless staging
runtime. Its Dockerfile passed the repository secret scan and all `605`
tests. The image ID was identical after loading the saved image archive into
the rootful production Docker runtime.

## Database promotion

A normal production PostgreSQL backup completed immediately before the
database change.

The following committed SQL passed first through the staging runner and then
through the production runner:

1. `012_add_resolution_profile_schedules.sql`;
2. `009_schedule_july_28_auto_preflight.sql`.

The seed verified exactly 15 `AUTO_PREFLIGHT` schedules and refused to finish
if any scheduled execution profile was not `DISABLED`.

After startup,
`verify_profile_lifecycle_auto_preflight.sql` passed in production. It
requires:

- all 15 exact schedules to remain `PENDING`;
- all 15 execution profiles to remain `DISABLED`;
- no `AUTO_LIVE` schedule;
- no `ACTIVE` schedule.

## Runtime services

All production workers use the immutable image above:

- `earnings-worker`;
- `notification-worker`;
- base `resolution-worker`;
- `profile-scheduler-worker`;
- `profile-readiness-worker`.

Only the readiness service was started from the trading overlay. The
overlay's `resolution-worker` configuration was not started. Purpose-built
runtime guards confirmed:

```text
scheduler_guard=passed
resolution_shadow_guard=passed
readiness_non_submitting_guard=passed
```

The guards check only exact non-secret modes and secret-file presence by name:

- scheduler automatic live activation is `0` and it has no master-key file;
- resolution mode is `shadow` and it has no master-key file;
- readiness live submission is `0` and its two required trading files are
  mounted.

Both name-only secret checks passed. The scheduler receives only
`DATABASE_APP_PASSWORD`; readiness receives exactly the database password,
master-key, and encrypted-key file names. No value was read or printed.

## Sanitized health evidence

Raw production logs were not returned. A tested filter first applied
`cbr_trading.secret_guard` and then retained only explicit health markers.
The resulting aggregate state was:

```text
profile lifecycle: auto_live=False, requested=0, activated=0,
                   blocked=0, expired=0, notifications=0
profile readiness: non-submitting, checked=0, ready=0, blocked=0
SEC source: connected=True, watches=19, errors=0
public polling: inactive
Strategy Ledger polling: inactive
resolution worker: no enabled in-window profiles
Telegram outbox: claimed=0, sent=0, failed=0
```

The counters are zero because the first preflight time has not arrived. The
earliest checked-in request is July 28 at `08:45 UTC` (`10:45` Budapest).
At that time the scheduler may request authenticated preparation and enqueue
Telegram lifecycle messages, but `AUTO_PREFLIGHT` cannot change an execution
profile to `ENABLED`.

## Safety boundary

No order was prepared by the live executor or submitted. No execution profile
was enabled. `PROFILE_SCHEDULER_AUTO_LIVE_ENABLED=0` remains installed.

The `Profile enabled` Telegram notification is implemented for the later
`AUTO_LIVE` stage, but cannot be produced by the currently seeded
`AUTO_PREFLIGHT` schedules. Dynamic live-profile refresh, aggregate risk
approval, and explicit live authorization remain separate future work.
