# Production authenticated preflight checkpoint

Date: 2026-07-26

## Reviewed release

- Source commit: `253230f`
- Production image:
  `codexpoly@sha256:2c408499ddd01367fe097586346bd6cbe5073f5c82b8831d4d642c839cf31c30`
- The image build passed the repository secret scan and 419 unit tests.
- The same digest passed staging shadow startup before production promotion.

## Account boundary

- Account name: `abccbaq`
- Public metadata is stored in `trading_account_metadata`.
- Venue: `polymarket_clob`
- Signature type: `2`
- The encryption master key and encrypted private key remain production
  file-secrets and are not stored in PostgreSQL.
- No legacy `trading_accounts` row is required.

## Preflight controls

- Only `earnings-nvts-2026q2` was temporarily enabled.
- The guarded read-only check confirmed exactly one enabled in-window profile.
- `RESOLUTION_ORCHESTRATOR_MODE=preflight`
- `RESOLUTION_SUPERVISION_ENABLED=0`
- `CBR_LIVE_TRADING_ENABLED=0`
- Maximum order quantity: `50`
- Maximum per-order notional: `50`
- Maximum aggregate prepared notional: `100`

## Aggregate evidence

The production worker:

- loaded both NVTS outcome books;
- derived authenticated CLOB API credentials;
- verified the configured SAFE wallet;
- checked collateral balance and allowance;
- loaded tick size and negative-risk status for both outcomes;
- pre-signed two orders;
- reported
  `Hosted resolution ready mode=preflight profiles=1 templates=2`.

No order was submitted.

## Cleanup

- The guarded restore SQL returned NVTS to its checked-in preparation window.
- The production invariant confirmed all execution profiles are `DISABLED`.
- `resolution-worker` was recreated from the base Compose file only.
- The worker returned to shadow mode with no enabled in-window profiles.
- The name-only checker confirmed that the base worker requires and receives
  only `DATABASE_APP_PASSWORD`; trading secret mounts were removed.
