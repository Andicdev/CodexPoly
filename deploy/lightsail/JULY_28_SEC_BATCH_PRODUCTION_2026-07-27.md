# July earnings SEC-first production checkpoint — 2026-07-27

## Reviewed release

- Source commit: `fd5db4d`.
- Clean source archive SHA256:
  `ee64774e755a054d8b32bd29eadf1bb088c9371aea14a43742d069e33121ffcd`.
- Image archive SHA256:
  `dc40d5f9a984bd5db5f612c3687a7263ca3d1a440c1756ff2d9609c7533529a7`.
- Immutable image:
  `codexpoly@sha256:10729f5c6a4432df0cc12a6c993ac5434c025a2ce287282cea30d162d9dfac9c`.

The clean VPS build passed the repository secret scan and all `595` tests.
The local working tree passed the same suite with one skip.

## Scope

The shared continuously connected SEC-API WebSocket now covers the ten
remaining reviewed earnings markets. Each route requires an initial 8-K,
Item 2.02, and EX-99.1 from the exact issuer CIK.

| Ticker | Scope | Market test | Official release estimate (UTC) |
| --- | --- | --- | --- |
| PYPL | `earnings:PYPL:2026Q2` | non-GAAP diluted EPS `> 1.28` | July 28 11:00 |
| UPS | `earnings:UPS:2026Q2` | non-GAAP adjusted diluted EPS `> 1.66` | July 28 10:00 |
| HLT | `earnings:HLT:2026Q2` | diluted EPS adjusted for special items `> 2.25` | July 28 10:00 |
| IVZ | `earnings:IVZ:2026Q2` | adjusted diluted EPS `> 0.66` | July 28 11:00 |
| KO | `earnings:KO:2026Q2` | comparable non-GAAP EPS `> 0.93` | July 28 10:55 |
| JBLU | `earnings:JBLU:2026Q2` | diluted EPS excluding special items and investment gains `> -0.68` | July 28 10:00 |
| SPGI | `earnings:SPGI:2026Q2` | adjusted diluted EPS `> 4.95` | July 28 11:15 |
| V | `earnings:V:2026Q3` | non-GAAP diluted EPS `> 3.22` | July 28 20:05 |
| F | `earnings:F:2026Q2` | adjusted non-GAAP diluted EPS `> 0.35` | July 28 20:05 |
| SBUX | `earnings:SBUX:2026Q3` | GAAP diluted EPS `> 0.69` | July 29 20:05 |

The SBUX Polymarket slug contains July 28, but Starbucks officially scheduled
the release for July 29 after market close. The rule retains the immutable
market slug and condition ID while using the official July 29 monitoring and
execution window.

## Historical parser evidence

Every parser was replayed against the issuer's official Q1 or prior fiscal
quarter SEC EX-99.1:

```text
PYPL accepted 1.34
UPS  accepted 1.07
HLT  accepted 2.01
IVZ  accepted 0.57
KO   accepted 0.86
JBLU accepted -0.87
SPGI accepted 4.97
SBUX accepted GAAP 0.45
V    accepted 3.31
F    accepted 0.14
```

The patterns select the issuer-specific reported field and fail closed for
guidance-only text, the wrong GAAP/non-GAAP basis, a missing fiscal period,
or conflicting values.

## Database state

The idempotent seed
`deploy/lightsail/seeds/008_add_july_28_sec_profiles.sql` and fail-closed check
`deploy/lightsail/checks/verify_july_28_sec_profiles.sql` passed through both
staging and production migration runners.

- All ten market rules are `SHADOW`.
- All ten execution profiles are `DISABLED`.
- No execution claim exists for any new scope.
- The seed does not update an existing profile unless it is already
  `DISABLED`.
- The seed cannot enable a profile or create a claim.

Every profile uses the common `abccbaq` default:

- YES and NO desired price `0.999`;
- quantity `50`;
- tick lifecycle `0.01 → 0.001`;
- at most one reprice.

The seven July 28 pre-market profiles have a broad `09:00–17:00 UTC` safety
window. Visa and Ford use `18:00–02:00 UTC`; Starbucks uses the same window
one day later.

## Runtime evidence

The immutable image and seed were promoted to rootless staging first. All ten
live network replays succeeded inside the staging container. The staging
worker then reported:

```text
watches=19
earnings_watches=18
mstr_watches=1
```

The same digest was deployed to all three production base workers:

- `earnings-worker`;
- `notification-worker`;
- `resolution-worker`.

Production reported the same 19 SEC watches. The resolution worker reported
no enabled in-window earnings or MSTR profiles. The trading overlay was not
started, public pollers remained profile-gated, and no order was prepared or
submitted.

## Safe next step

Perform guarded authenticated preflight and live activation as a separate
operation. The morning group and the evening group should be activated and
audited separately. Company IR and press-wire discovery can be added per
issuer later without changing these market rules or SEC parsers.
