# Source polling gate and notification outbox checkpoint

Date: 2026-07-27 (Europe/Budapest)

## Scope

The hosted source runtime now separates three concerns:

- the shared SEC-API WebSocket remains connected independently of execution
  profile status;
- external HTTP polling is allowed only while at least one matching
  resolution profile is `ENABLED` and inside its preparation window;
- confirmed source events are inserted into a durable, idempotent outbox and
  delivered by a separate Telegram worker.

Telegram network latency, failure, and retry therefore cannot block SEC
stream consumption, parsing, canonical fact persistence, strategy evaluation,
or order execution.

## Reviewed release

- source commit: `421a278`;
- clean release archive SHA256:
  `0dd3f9495e4514e06b21728a47d064ce491b3ce4864944109f26860c58422782`;
- immutable image:
  `codexpoly@sha256:fb2be19a7eecf1c63598c1d8caeec347741f3e45ea0fb9994548ef0eb4b3be08`.

The clean Docker build repeated the repository secret scan and passed 532
clean-commit tests. The full local working-tree run passed 547 tests with one
skip; the additional local tests belong to separate uncommitted account-key
work and were not included in this release.

## Database

Additive migration `010_add_source_notification_outbox.sql` was applied first
to staging and then to production through the fixed stdin-only runners.
`SqlAlchemyNotificationOutboxStore.ensure_ready()` passed in both
environments. The migration creates only `source_notification_outbox` and
does not alter or remove a legacy field or table.

## Staging gate proof

With every execution profile disabled, the source reported:

```text
connected=True watches=4
ledger_active=False ledger_profiles=0
ledger_connected=False ledger_polls=0
```

Exactly one guarded MSTR profile was then temporarily enabled in staging
shadow. The source changed to:

```text
Strategy Ledger polling state active=True profiles=1
```

After 12 conditional Ledger polls, the guarded restore returned all three
MSTR profiles to `DISABLED`. The source then reported:

```text
Strategy Ledger polling state active=False profiles=0
ledger_connected=False ledger_polls=12 ledger_accepted=0 errors=0
```

The staging resolution worker was recreated after the restore and confirmed
that neither earnings nor MSTR has an enabled in-window profile.

## Production state

The base production `earnings-worker` and `resolution-worker` were recreated
from the immutable image. The trading overlay was not used. Production now
reports:

```text
SEC shadow stream connecting watches=4
Strategy Ledger polling state active=False profiles=0
Hosted resolution has no enabled in-window profiles
Hosted MSTR resolution has no enabled in-window profiles
```

Production Compose was saved as `compose.before-421a278.yml` before the
replacement. Staging and production source events can now accumulate durable
pending notifications even while Telegram delivery is unavailable.

## Remaining human-only action

The name-only checks found that both environments currently lack
`TG_BOT_TOKEN` and `TELEGRAM_INGEST_CHAT_ID`. The production
`notification-worker` was therefore intentionally not started.

An operator must install those two production secrets through the existing
hidden-prompt installer. After both name-only checks pass, the reviewed
production Compose can start only `notification-worker`; no earnings,
resolution, profile, or trading change is required.
