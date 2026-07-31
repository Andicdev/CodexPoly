# July 31 PRE_MARKET production checkpoint

Recorded on 2026-07-31 after the guarded rollout of BEN, CBOE, CVX, CL,
MRNA, and ARES alongside the existing XOM profile.

## Immutable release

- Application commit: `d19d585`
- Production image:
  `codexpoly@sha256:7aa455022d54f96dde0e0e221be2d9cbf21ce46ee08619e8d06a3d5264d6bae1`
- Source archive SHA256:
  `5e6ece9f54267ecd584b4e5d5a2632aa64440dd43c2c75784c9eb67b2a922db5`
- Docker archive SHA256:
  `821d54762789797e0fa7ab9adb258130648ff69df5a279b1e51174c407824d4e`
- The image build passed the repository secret scan and all 1011 tests.

The earnings, resolution, readiness, and scheduler workers were moved to the
new image. PostgreSQL and the notification worker were not restarted.

## Database and lifecycle state

- Additive seed `038_add_july_31_premarket_batch.sql` was applied.
- Guarded migration `045_arm_july_31_premarket_batch.sql` was applied.
- BEN, CBOE, CVX, CL, MRNA, and ARES are `AUTO_LIVE`, initially
  `PENDING`, with execution profiles kept `DISABLED` until scheduler
  activation.
- XOM completed authenticated preflight at `2026-07-31T08:15:05Z` and was
  `READY` with its execution profile still `DISABLED`.
- Live caps are quantity `100`, per-order notional `100`, and aggregate
  notional `1000`.
- The seven reviewed profiles total `699.3` maximum configured notional.

## Source health

The earnings source worker was restarted after the seed so its long-lived SEC
WebSocket could preload the new CIK filters. It connected with 38 total
watches: 37 earnings watches plus the existing MSTR watch. The first
sanitized connection marker reported no source error.

Public-release and SEC-current polling remain profile-gated. They are expected
to remain inactive while profiles are disabled and to start after scheduler
activation.

## Rollout correction

The first Compose recreation inherited default `0` values for the
resolution live/trading/supervision flags and scheduler auto-live flag. The
sanitized scheduler heartbeat exposed `auto_live=False`, and the live arming
guard failed closed. No profile was enabled and no order was submitted.

Resolution and scheduler were immediately recreated with:

- resolution mode `live`;
- supervision enabled;
- trading enabled;
- scheduler auto-live enabled;
- the reviewed `100 / 100 / 1000` caps.

After the correction, the guarded live arming migration passed, the resolution
heartbeat reported `mode=live`, and the scheduler heartbeat reported
`auto_live=True`.

## Remaining read-only gates

- Before 08:30 UTC:
  `verify_july_31_premarket_batch_auto_live_armed.sql`
- From 08:30 to 08:45 UTC:
  `verify_july_31_premarket_seven_preflight_ready.sql`
- From 08:45 UTC until the earliest expected signal:
  `verify_july_31_premarket_seven_live_active.sql`

The thread heartbeat owns these remaining checks and must not bypass
`BLOCKED` or `ERROR` states.
