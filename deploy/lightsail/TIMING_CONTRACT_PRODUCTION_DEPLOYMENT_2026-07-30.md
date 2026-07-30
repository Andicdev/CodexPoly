# Timing contract production deployment — 2026-07-30

Status: deployed and healthy.

## Scope

- Applied additive migration
  `019_add_earnings_release_timing.sql`.
- Applied additive migration
  `020_add_resolution_timing_contract.sql`.
- Verified the resulting schema through
  `verify_resolution_timing_contract_schema.sql`.
- Recreated the five production workers from the staging-tested immutable
  image:
  `sha256:1cadb283136a3235a8404663a4fdd322c306d60564af3c6162a6a37691408df4`.

The image was built from commit `f9629f4`. The exported image was loaded into
the production Docker daemon without rebuilding it.

## Guarded rollout evidence

Before the restart,
`verify_safe_worker_restart_window.sql` confirmed that there were:

- no enabled execution profiles;
- no active or imminently activating schedules;
- no pending execution claims;
- no active order supervision or repricing groups.

Existing terminal order-group rows and any venue-side resting orders were not
cancelled or modified by this rollout.

After the restart:

- earnings, resolution, readiness, scheduler, and notification workers all
  reported the expected image digest;
- all five workers were running with restart count `0`;
- SEC-API WebSocket reported `connected=True`;
- scheduler reported `auto_live=True`;
- public, SEC-current, Strategy Ledger, earnings resolution, MSTR, and FED
  profile-gated paths all reported zero active profiles;
- the final safe-restart verification passed again.

Trading limits remained `100 / 100 / 1000`.

