# Profile lifecycle completion production rollout

## Reviewed release

- Application commit: `c68de3a`.
- Clean source archive SHA256:
  `221cff07c2bf2d8f19e81608d08342bf19577b931b4fbac435e4e85b2ddc84b9`.
- Image archive SHA256:
  `173b03f09c330080c9d145ff9f766a0b401c064805b0b85df6e125b782ac582e`.
- Immutable production image:
  `codexpoly@sha256:c4240d8500b1b477b7be5d1878c43add945895cb84643d3c7edff42647cc2146`.

The image was built from the clean Git archive. Its Docker build independently
passed the repository secret scan and all 746 tests.

## Staging promotion

Migration 017 was applied first. The initial image start then stopped
fail-closed with the sanitized type `EarningsStoreError`: commit `c68de3a`
also contains the previously undeployed source-telemetry code and therefore
requires additive migration 016.

The staging workers were immediately restored to their previous reviewed image
`sha256:cc8cf9fa5ce94ffd2f74f8e0f1ab6c9e979ebd7badf0463fa03830b24babe838`.
Migration 016 was applied, both schema guards passed, and the new image was
started again. After the corrected promotion:

- earnings and resolution workers were running on the new immutable image
  with zero restarts;
- the SEC stream connected with 33 watches;
- the hosted resolution worker remained in shadow with no enabled profiles;
- the synthetic earnings path completed
  `Source -> ResolutionSignal -> Strategy -> OrderIntent -> PreparedExecutor`;
- the selected result was `DRY_RUN`, `order_submitted=false`, and the fixture
  was finalized.

Production was not changed until this staging run passed.

## Production migration

The guarded production migration runner applied, in order:

1. `016_add_earnings_source_telemetry.sql`;
2. `017_add_completed_profile_schedule_state.sql`.

Both migrations are additive and backward-compatible with the previous
production image. Read-only guards then confirmed the two telemetry tables,
their exact columns and indexes, and all three lifecycle constraints accepting
`COMPLETED`.

## Production image rollout

The exact staging image archive was loaded into the rootful production Docker
runtime and retained for audit and rollback. These recoverable Compose copies
were created before recreation:

- `compose.before-c68de3a.yml`;
- `compose.trading.before-c68de3a.yml`.

All five production workers now use the exact immutable image:

- `earnings-worker`;
- supervised live `resolution-worker`;
- `notification-worker`;
- `profile-scheduler-worker`;
- non-submitting `profile-readiness-worker`.

The existing live guards were preserved: quantity `100`, per-order notional
`100`, aggregate notional `1000`, supervision enabled, trading enabled, and
scheduler automatic live activation enabled.

## Post-rollout evidence

All five containers were running for more than two minutes on the reviewed
digest with zero restarts. Raw logs were not returned. The committed runtime
log sanitizer applied `cbr_trading.secret_guard` before retaining explicit
health markers.

The sanitized and guarded evidence confirmed:

- SEC stream `connected=True`, 14 current watches, and `errors=0`;
- fully-live hosted resolution heartbeat was fresh;
- scheduler reported `auto_live=True` with no activation, block, or expiry
  error during the rollout;
- readiness remained non-submitting;
- notification delivery reported 6 claimed, 6 sent, and 0 failed;
- the separate FED July profiles and schedules remained disarmed, with no FED
  execution claim;
- the `COMPLETED` schedule/profile/audit invariants passed.

No resolution signal was processed and no order was submitted by this
deployment.

## Historical boundary

The read-only July 29 diagnostic still reproduces at least one historical
schedule in `ACTIVE` or `BLOCKED` with an already `EXECUTED` claim. This is
expected: the rollout adds correct behavior for new terminal executions but
does not infer or rewrite historical lifecycle state.

Any historical reconciliation must be a separate guarded migration that maps
each exact execution claim to its schedule, preserves existing orders, and
does not reinterpret a source fact as permission to trade.
