# HLT company IR production checkpoint

Date: 2026-07-27

## Reviewed release

- Implementation commit: `1d1445a`.
- Clean source archive SHA256:
  `776c12aec2a57abe87c278acfc31d6364cceabe207b5940c7765fa05da00a56e`.
- Image archive SHA256:
  `f63839b638cef0ca55a10430852fde36ec90704d2fca22d27a8ab041538d243e`.
- Immutable image:
  `codexpoly@sha256:540ae21865b0aae922fd0eeb815b532bde0dfbbc91c0ce7276b38b6975865ffe`.

The clean Docker build passed the repository secret scan and all `628`
tests. The image archive checksum was recorded before the same image was
loaded into the rootful production Docker runtime.

## Source paths

HLT now has two official transports:

1. the continuously connected shared SEC-API WebSocket and Item 2.02 /
   EX-99.1 route;
2. the official Hilton Stories RSS feed and the full HTML release on
   `stories.hilton.com`.

The Hilton listing requires `Hilton`, `Second Quarter`, and `Results` in the
title. Announcement headlines containing `Announces` or `Release Date` are
explicitly rejected. Full-document URL and redirect validation are restricted
to the exact `stories.hilton.com` host.

Public polling remains profile-window gated. The worker makes no Hilton RSS
or HTML request while `earnings-hlt-2026q2` is disabled.

## Parser evidence

The immutable image replayed Hilton's real first-quarter 2026 HTML release
from the official company site. The parser accepted adjusted diluted EPS
`2.01` and did not select the forward guidance range that followed it.

This exercises the production transport boundary:

```text
Hilton Stories RSS -> official HTML -> Hilton adjusted diluted EPS parser
```

## Database promotion

The source-only seed and read-only invariant check passed in staging. A fresh
production PostgreSQL backup completed before the same seed and check passed
in production.

The guard confirmed:

- the HLT profile remains `DISABLED`;
- its schedule remains `AUTO_LIVE / PENDING`;
- authenticated preflight remains `2026-07-28 08:45 UTC`;
- activation remains `2026-07-28 09:00 UTC`;
- deactivation remains `2026-07-28 17:00 UTC`;
- order prices remain `0.999 / 0.999` and quantity remains `50`;
- no validated fact, execution claim, or active order group exists for HLT.

The complete 15-profile AUTO_LIVE invariant and fresh supervised live
resolution heartbeat also passed after promotion.

## Runtime promotion

Only `earnings-worker` was recreated in staging and production. The
notification, readiness, scheduler, and supervised live resolution workers
were not restarted.

The production SEC source reconnected with `19` total watches: `18` earnings
watches and `1` MSTR watch. Public-source polling remains inactive until an
in-window earnings profile is enabled.

No order was prepared or submitted while the HLT source was added.
