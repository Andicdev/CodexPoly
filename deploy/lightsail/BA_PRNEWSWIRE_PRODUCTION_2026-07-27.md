# BA PR Newswire production checkpoint

Date: 2026-07-27

## Reviewed release

- Source implementation commit: `5cd7288`.
- Corrected BA schedule-guard commit: `9d81c44`.
- Clean source archive SHA256:
  `994e27615cda5631c87131d716e3556e8517548ea1e97e511f2c3007c548a7b1`.
- Image archive SHA256:
  `ede8fb8c7964d6151e64ea40ef6fe0c7a785bb8a40cabc394df700eba545d5d0`.
- Immutable image:
  `codexpoly@sha256:01e33b46d61ddc8ca7493d6eb637d21b6391ecee0e19125c8ffbd4e6385e06ff`.

The clean Docker build passed the repository secret scan and all `624`
tests. The image archive checksum was verified before the same image was
loaded into the rootful production Docker runtime.

## Source paths

BA now has three official transports:

1. the continuously connected shared SEC-API WebSocket and Item 2.02 /
   EX-99.1 route;
2. Boeing investor-relations RSS and the full company release;
3. PR Newswire RSS and the full wire release.

The PR Newswire listing uses exact title requirements for `Boeing`,
`Second Quarter`, and `Results`, and rejects announcement and deliveries
headlines. URL and redirect validation remain restricted to the exact
`www.prnewswire.com` host.

Public polling remains profile-window gated. No Boeing IR or PR Newswire HTTP
request is made while `earnings-ba-2026q2` is disabled.

## Parser evidence

The initial full PR Newswire replay was deliberately quarantined because the
generic labelled parser observed both current-quarter and first-half values.
The BA parser was then narrowed to Boeing's primary headline pair: reported
GAAP EPS followed by reported core EPS. Comparative tables alone cannot
resolve the market.

The final immutable image replayed two real official documents from the VPS:

```text
PR Newswire  2025Q2  accepted  core EPS  -1.24
Boeing IR    2026Q1  accepted  core EPS  -0.20
```

This verifies the new transport without regressing the existing company
source.

## Database promotion

The first staging attempt failed closed because its draft guard used the
earliest morning schedule instead of BA's own schedule. The transaction made
no change. The corrected guard uses:

- authenticated preflight at `2026-07-28 09:45 UTC`;
- activation at `2026-07-28 10:00 UTC`;
- deactivation at `2026-07-28 17:00 UTC`.

The corrected source-only seed and read-only invariant check passed in
staging. A fresh production PostgreSQL backup then completed before the same
seed and check passed in production.

The check confirmed that the BA profile remains `DISABLED`, its schedule
remains `AUTO_LIVE / PENDING`, and no validated fact, execution claim, or
active order group exists for the scope.

## Runtime promotion

Only `earnings-worker` was recreated in staging and production. Production
now runs that service on the new immutable image. The notification,
readiness, scheduler, and supervised live resolution workers were not
restarted and remain on the previously reviewed lifecycle image.

The production SEC source reconnected with `19` total watches:
`18` earnings watches and `1` MSTR watch. Its first sanitized heartbeat
reported `connected=True`, `errors=0`, and `public_active=False`, which is
the expected state while no in-window earnings profile is enabled.

The final database invariants passed again after runtime promotion, and the
supervised live resolution heartbeat remained fresh.

No order was prepared or submitted while the source was added.
