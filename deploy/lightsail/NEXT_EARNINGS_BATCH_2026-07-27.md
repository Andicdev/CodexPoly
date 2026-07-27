# BA, CZR, and CSGP earnings shadow checkpoint — 2026-07-27

## Reviewed release

- Source commit: `6cdff9b`.
- Clean source archive SHA256:
  `bc1968b7ba5449e6e0c8a7d893fecd905ae8418b642af36a1abd3deec4522eb8`.
- Image archive SHA256:
  `aebfbad45d1e236ab6ef1ef88c2dc65690db3da70c1cb9dc03fe28456cdd218b`.
- Immutable image:
  `codexpoly@sha256:fc2b64267456ad2d57c95d9ea22946bf10d13b55d282508cc92c47b41155d516`.

The clean Docker build passed the repository secret scan and all `584`
tests. The same image was loaded into rootless staging and retained for the
rootful production base stack.

## Historical release replays

The staging earnings container fetched the real official 2026 first-quarter
release for each company and ran it through the production parser boundary:

```text
BA   accepted  core diluted EPS      -0.20
CZR  accepted  GAAP diluted EPS      -0.48
CSGP accepted  GAAP diluted EPS       0.01
```

The CoStar replay also verifies that adjusted/non-GAAP EPS is not selected
for the GAAP market. Each parser remains fail-closed when the expected fiscal
period, metric label, basis, or unique value cannot be established.

## Database state

The idempotent seed
`deploy/lightsail/seeds/006_add_ba_czr_csgp_earnings.sql` and fail-closed
check `deploy/lightsail/checks/verify_ba_czr_csgp_earnings.sql` passed through
both the staging and production migration runners.

| Ticker | Rule | Market test | Profile | Prepare window (UTC) |
| --- | --- | --- | --- | --- |
| BA | `ba-2026q2-nongaap-eps-neg0pt32` | primary headline core/non-GAAP diluted EPS `> -0.32` | `earnings-ba-2026q2` | July 28 10:00–17:00 |
| CZR | `czr-2026q2-gaap-eps-0pt05` | official GAAP diluted EPS `> 0.05` | `earnings-czr-2026q2` | July 28 18:00–July 29 02:00 |
| CSGP | `csgp-2026q2-gaap-eps-0pt10` | official GAAP diluted EPS `> 0.10` | `earnings-csgp-2026q2` | July 28 18:00–July 29 02:00 |

All three rules are `SHADOW`. All three execution profiles are `DISABLED`.
The common default template is preserved:

- account `abccbaq`;
- YES and NO desired price `0.999`;
- quantity `50`;
- tick lifecycle `0.01 → 0.001`;
- at most one reprice.

No execution claim was created and no order was prepared or submitted.

## Source paths

Each rule has two independent official transport paths:

1. the continuously connected shared SEC-API WebSocket, followed by the
   reviewed Item 2.02 / EX-99.1 document route;
2. the company's investor-relations RSS feed, followed by the full official
   company release document.

Boeing's PR Newswire and the Caesars/CoStar Business Wire publications are
mirrored by the company IR releases. They are not counted as independent
third transports in this checkpoint.

## Runtime evidence

The staging and production base workers run the reviewed immutable image.
The trading overlay was not started and trading secrets were not mounted.

Both environments reported:

```text
SEC watches=8
earnings_watches=7
mstr_watches=1
public_active=False
public_scopes=0
ledger_active=False
enabled resolution profiles=0
```

The SEC WebSocket remains connected while public RSS polling stays inactive
until an earnings profile is explicitly enabled inside its preparation
window.

## Activation split

BA is a pre-market release and requires a separate guarded morning preflight
and explicit live approval before its July 28 window. NXPI, CZR, and CSGP are
the post-market group. This checkpoint does not enable any of them.
