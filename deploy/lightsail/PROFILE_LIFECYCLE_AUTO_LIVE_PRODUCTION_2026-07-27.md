# Profile lifecycle AUTO_LIVE production checkpoint

Date: 2026-07-27

## Reviewed release

- Runtime source commit: `b792c08`.
- Deployment-check commit: `0379b5e`.
- Clean source archive SHA256:
  `1547236f77c403b5c2ce7be7c6db2fd05b83673cca29ca8d61bf1d551fba924a`.
- Image archive SHA256:
  `2535c768371eaff2e065f4cabea5a292d9167437cee8a51673284a31f2396f4f`.
- Immutable image:
  `codexpoly@sha256:126542b82129ee691c61217edbc7f2df9148e469603977ebdccefa77a68751c0`.

The image was built from a clean `git archive` in the rootless staging
runtime. Its Dockerfile passed the repository secret scan and all `616`
tests. The image archive checksum and image digest matched after loading it
into the rootful production Docker runtime.

## Database promotion

A production PostgreSQL backup completed immediately before the database
change.

Migration `013_add_resolution_runtime_heartbeats.sql`, seed
`010_arm_july_28_auto_live.sql`, and the fail-closed AUTO_LIVE checks passed
first in staging and then in production.

The production seed changed exactly 15 reviewed schedules from
`AUTO_PREFLIGHT` to `AUTO_LIVE`. It did not enable an execution profile.
After scheduler startup:

- all 15 schedules remained `PENDING`;
- all 15 execution profiles remained `DISABLED`;
- their reviewed worst-selected-outcome notional remained below `1000`.

## Runtime services

All five production workers use the immutable image:

- `earnings-worker`;
- `notification-worker`;
- `profile-readiness-worker`;
- `profile-scheduler-worker`;
- `resolution-worker`.

The scheduler has automatic activation enabled with aggregate cap `1000` and
has no trading-key secret mount. The resolution worker runs in `live` mode
with supervision and trading enabled, quantity cap `50`, per-order notional
cap `50`, and aggregate cap `1000`.

Purpose-built guards checked only non-secret settings and secret-file
presence by name:

```text
scheduler_live_guard=passed
resolution_live_guard=passed
readiness_non_submitting_guard=passed
```

The database also confirmed a fresh `hosted-resolution` heartbeat with
`mode=live`, supervision enabled, and trading enabled.

## Sanitized health evidence

Raw production logs were not returned. The committed sanitizer first applied
`cbr_trading.secret_guard` and retained only explicit health markers.

Production reported:

```text
profile lifecycle: auto_live=True, requested=0, activated=0,
                   blocked=0, expired=0, notifications=0
SEC source: connected with watches=19, earnings_watches=18, mstr_watches=1
hosted resolution: no enabled in-window earnings or MSTR profiles
```

No order was prepared or submitted during rollout.

## First scheduled window

The 15 AUTO_LIVE schedules cover the July 28 morning and evening earnings
groups plus Starbucks on July 29. The earliest scheduler preflight is July 28
at `08:45 UTC`; the earliest execution windows open at `09:00 UTC`.

NVTS reports on July 27 and has a separate checked-in profile with execution
window `19:00 UTC` through `03:00 UTC`. It was not one of the 15 schedules
armed by this rollout. Its separately approved AUTO_LIVE promotion is
recorded in `NVTS_AUTO_LIVE_PRODUCTION_2026-07-27.md`.
