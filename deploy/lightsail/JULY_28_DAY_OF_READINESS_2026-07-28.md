# July 28 day-of readiness checkpoint

Date: 2026-07-28

## NVTS closeout

The NVTS AUTO_LIVE window completed before this checkpoint. The scheduler
expired the schedule and disabled the execution profile. A fresh production
PostgreSQL backup was taken, then the guarded migration
`014_switch_nvts_ir_feed_to_gcs.sql` and its read-only verification both
completed successfully.

The production NVTS company-IR transport now uses the official GCS endpoint.
No NVTS profile or order was enabled by that migration.

## Production invariants

The following fail-closed checks passed against production:

- live supervised resolution runtime;
- all 15 remaining earnings schedules armed as `AUTO_LIVE / PENDING`;
- earnings release catalog for July 28;
- SEC rules and profiles for the July 28 batch;
- BA, CZR, CSGP, RCL, and NXPI rule/profile guards;
- BA PR Newswire, HLT company-IR, and NVTS GCS source guards.

The July 28 SEC batch check was updated to reflect the previously approved
HLT company-IR source. It still requires SEC for HLT and still rejects an
unexpected second source on the other generic SEC-only rules.

## Sanitized runtime health

At approximately `2026-07-28 07:36 UTC`:

```text
earnings:     connected=True, watches=19, public_active=False
resolution:   mode=live, earnings profiles=0, MSTR profiles=0
scheduler:    auto_live=True, blocked=0, expired=1
readiness:    checked=1, ready=1, blocked=0
notification: claimed=7, sent=7, failed=0
```

The earnings worker's cumulative error counter remained unchanged across
successive heartbeats. Those historical errors came from the completed NVTS
public-polling window; there is no continuing error growth.

All five worker containers were `Up`. Earnings and resolution use immutable
image:

```text
codexpoly@sha256:d603719cc477e2b0b9c6ed7c04ca8933bdb036ab43b9ffdf6c00024678f532fa
```

## Today's activation timeline

All times below are UTC. Budapest is UTC+2 on this date.

- `08:45`: authenticated preflight for PYPL, UPS, HLT, IVZ, KO, RCL,
  JBLU, and SPGI;
- `09:00`: those eight profiles become eligible for AUTO_LIVE activation;
- `09:45`: authenticated preflight for BA;
- `10:00`: BA becomes eligible for AUTO_LIVE activation;
- `17:45`: authenticated preflight for CZR, CSGP, V, F, and NXPI;
- `18:00`: those five profiles become eligible for AUTO_LIVE activation.

SBUX belongs to the next window: preflight on July 29 at `17:45 UTC` and
activation at `18:00 UTC`.

No early authenticated preflight was forced during this checkpoint. The
readiness worker remains responsible for the scheduled checks, and a failed
or stale readiness result must block AUTO_LIVE activation.

No order was submitted during the NVTS migration or this readiness audit.
