# July 29 ARCC and PAG parser rollout

## Scope

This checkpoint promotes the ARCC and PAG parser fixes from commit
`ef8e45716bb6` through the staging-first worker rollout. It does not replay a
source event into production, alter a historical fact or claim, enable a
profile, submit an order, or change the database schema.

The production restart was guarded by
`checks/verify_safe_worker_restart_window.sql`. The check fails closed when
there is any enabled execution profile, active schedule, schedule activating
within 15 minutes, pending execution claim, or active/repricing order group.
It passed before the release image was loaded, immediately before the worker
restart, and after the restart.

## Reproducible artifacts

- source commit: `ef8e45716bb6`;
- source archive SHA256:
  `7f6845301af88d6dac082108fffc248b6a5954a05cfecf997115f516f18629fe`;
- immutable image ID:
  `sha256:4ef4fbbdea1867e39beddaee7828f986f86ba0b2d44130b05e5dc0b423a6c747`;
- image archive SHA256:
  `66c2978305a97533b921ae0759835b35edb8c48681593194ca679b057280eefe`.

The image was built from `git archive`, excluding the local worktree. Its
Docker build completed the repository secret scan and all 751 unit tests.

## Staging evidence

The staging earnings and resolution workers were recreated on the immutable
image in shadow mode. Full public production documents were fetched once and
passed directly to parsers inside that image:

- ARCC: `accepted`, `official_ares_capital_core_eps`, value `0.47`, parser
  version `2`;
- PAG: `accepted`, `official_penske_automotive_gaap_diluted_eps`, value
  `3.96`, parser version `2`.

The staging synthetic earnings path completed through:

`EarningsResolutionSource -> ResolutionSignal -> NumericThresholdStrategy ->
OrderIntent -> DryRunPreparedExecutor`

The result was one completed `DRY_RUN`, zero failures, and
`order_submitted=false`. The synthetic fixture was finalized. Staging
heartbeats then showed the SEC stream connected, no active profile-gated
polling, no active resolution profiles, and zero earnings errors.

## Production promotion

The installed production Compose files were byte-identical to the clean
release copies. Backup copies were retained as:

- `/opt/codexpoly/production/apps/workers/compose.before-ef8e457.yml`;
- `/opt/codexpoly/production/apps/workers/compose.trading.before-ef8e457.yml`.

The Compose model validated before use. All five workers were recreated on
the immutable image while preserving the reviewed live guards:

- orchestrator mode `live`;
- supervision enabled;
- trading enabled;
- scheduler automatic live activation enabled;
- quantity cap `100`;
- per-order notional cap `100`;
- aggregate notional cap `1000`.

After rollout, earnings, notification, scheduler, resolution, and readiness
workers were all running on the exact image with restart count zero.
Sanitized allowlisted logs confirmed:

- SEC stream connected with zero errors;
- profile-gated public and SEC polling inactive with no active profiles;
- live resolution heartbeat fresh with zero managed profiles;
- notification heartbeat with zero failures;
- scheduler heartbeat with automatic live activation enabled and no
  requested, blocked, or expired transitions;
- readiness heartbeat with no blocked profiles.

## Post-rollout invariants

The following guarded read-only production checks passed:

- fresh live resolution heartbeat with supervision and trading enabled;
- completed schedule/profile lifecycle invariants;
- July 29 historical completion reconciliation;
- July 29 FED profiles and claims remain disarmed;
- safe worker restart window remains true.

No production migration, source replay, profile activation, execution claim,
order submission, order cancellation, or historical-record rewrite was part
of this rollout.
