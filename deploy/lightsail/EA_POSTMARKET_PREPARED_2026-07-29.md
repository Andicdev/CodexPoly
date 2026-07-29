# EA POST_MARKET prepared — 2026-07-29

Only the Electronic Arts fiscal Q1 2027 event was added. META, MSFT, QCOM,
FED, and every other profile were left unchanged.

## Reviewed event

- Polymarket market:
  `ea-quarterly-earnings-gaap-eps-07-29-2026-0pt8`
- Resolution metric: GAAP diluted EPS
- Rule: reported value `> 0.80` resolves YES
- Reporting period: fiscal Q1 2027, ended June 30, 2026
- Estimated publication: approximately `2026-07-29T20:05:00Z`
- Official conference call: none scheduled
- Catalog schedule confidence: `ESTIMATED`

EA's official IR calendar did not list an upcoming event. The market remained
active and no July 29 earnings 8-K or financial-results release existed at
preparation time. EA's previous two earnings 8-K filings were accepted at
approximately `20:07Z` and `20:09Z`; that evidence is the basis for the
estimated window. This uncertainty is retained in catalog and schedule
metadata rather than being represented as a confirmed announcement.

## Source paths

The EA rule has four detection paths:

1. persistent SEC-API WebSocket for the EA 8-K / Item 2.02 / EX-99.1;
2. profile-gated official SEC current-filings polling;
3. profile-gated EA investor-relations press-release RSS;
4. profile-gated Business Wire RSS.

The parser selects the first `Diluted earnings per share` row in EA's primary
quarterly financial highlights table. EA repeats that label in a later
five-quarter comparison table, so collecting every occurrence would create a
false conflict. A replay against EA's real Q3 FY26 EX-99.1 accepted GAAP
diluted EPS `0.35`. Tests also cover the repeated-table shape.

## Execution profile

- Profile: `earnings-ea-2027q1`
- Account: `abccbaq`
- YES desired price: `0.999`
- NO desired price: `0.999`
- Quantity: `100`
- Lifecycle: `reprice_on_tick_change`
- Tick transition: `0.01 -> 0.001`
- Maximum reprices: `1`
- Prepare from: `2026-07-29T18:00:00Z`
- Expires at: `2026-07-30T02:00:00Z`
- Prepared profile status: `DISABLED`
- Prepared schedule mode/state: `AUTO_PREFLIGHT / PENDING`

The per-outcome reviewed notional is `99.9`, below the aggregate cap `1000`.
A separate explicit authorization is required before changing the schedule to
`AUTO_LIVE`.

## Verification and rollout

- Source commit: `b19b548`
- Source archive SHA256:
  `e72aa2696a139902b03199833a683425582e96e8056753f3b88b270bc2c32911`
- Immutable image:
  `sha256:9881b0a925f8224c7c418ac06c4bc56ca6bbc241d6cff39677a7d964e23f2f9c`
- Image archive SHA256:
  `b15ec897988724902683abfaa44cb692a565eff4224483470291f38415694752`
- Local and image secret scans passed.
- The complete unit suite passed: `779` tests, `1` skipped.
- The EA-only seed and read-only invariant check passed in staging.
- Both staging shadow workers started on the new image.
- The staging SEC stream reported `33` earnings watches and one MSTR watch.
- The same disabled/AUTO_PREFLIGHT seed and read-only check passed in
  production.
- A manual authenticated non-submitting preflight prepared and pre-signed
  both outcome templates.
- The preflight reported `order_submitted=false`,
  `executor_execute_called=false`, and maximum prepared notional `198.0`.
- The production safe-restart guard passed.
- Only the production `earnings-worker` was recreated on the new immutable
  image.
- Sanitizer-first logs reported `17` earnings watches, one MSTR watch, and no
  startup failure marker.
- Production retained no validated EA fact or execution claim.

## Live arming

After separate explicit authorization,
`deploy/lightsail/live/025_arm_ea_july_29_postmarket.sql` was applied with
limits `100 / 100 / 1000`.

The immediate read-only armed invariant confirmed:

- schedule mode/state: `AUTO_LIVE / PENDING`;
- profile status: `DISABLED`;
- `armed_for_live=true`;
- a fresh live resolution heartbeat with supervision and trading enabled;
- no validated EA fact, execution claim, or active order group;
- no lifecycle error.

The scheduler remains responsible for authenticated preflight at `17:45 UTC`
and profile activation at `18:00 UTC`. No order was submitted while arming.
