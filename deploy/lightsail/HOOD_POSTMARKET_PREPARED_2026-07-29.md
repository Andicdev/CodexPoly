# HOOD POST_MARKET prepared — 2026-07-29

Only the Robinhood Q2 2026 event was added. Other production profiles were
left unchanged.

## Reviewed event

- Polymarket market:
  `hood-quarterly-earnings-gaap-eps-07-29-2026-0pt43`
- Resolution metric: GAAP diluted EPS
- Rule: reported value `> 0.43` resolves YES
- Official release: after market close on July 29, 2026
- Estimated publication: approximately `2026-07-29T20:05:00Z`
- Conference call: `2026-07-29T21:00:00Z`
- Schedule status: `CONFIRMED`

## Source paths

The HOOD rule has four detection paths:

1. persistent SEC-API WebSocket for the 8-K / Item 2.02 / EX-99.1;
2. profile-gated official SEC current-filings polling;
3. profile-gated Robinhood investor-relations RSS;
4. profile-gated GlobeNewswire earnings RSS.

The existing parser was replayed against Robinhood's real Q1 2026 HTML
release and accepted GAAP diluted EPS `0.38`.

## Execution profile

- Profile: `earnings-hood-2026q2`
- Account: `abccbaq`
- YES / NO desired price: `0.999`
- Quantity: `100`
- Lifecycle: `reprice_on_tick_change`
- Tick transition: `0.01 -> 0.001`
- Maximum reprices: `1`
- Prepare from: `2026-07-29T18:00:00Z`
- Expires at: `2026-07-30T02:00:00Z`
- Profile status: `DISABLED`
- Schedule mode/state: `AUTO_PREFLIGHT / PENDING`

## Verification

- Commit: `ab82d9b`
- Secret scan passed.
- The complete unit suite passed: `784` tests, `1` skipped.
- The seed and read-only invariant check passed in staging.
- The same disabled/AUTO_PREFLIGHT seed and check passed in production.
- A manual authenticated non-submitting preflight prepared and pre-signed
  both outcome templates.
- Preflight reported `order_submitted=false`,
  `executor_execute_called=false`, and maximum prepared notional `198.0`.
- The production safe-restart guard passed.
- Only the production earnings worker was restarted on the existing immutable
  image `sha256:9881b0a925f8224c7c418ac06c4bc56ca6bbc241d6cff39677a7d964e23f2f9c`.
- Sanitizer-first logs reported `18` earnings watches, one MSTR watch, and no
  startup failure marker.
- No validated HOOD fact or execution claim exists.

## Deliberately not applied

`deploy/lightsail/live/026_arm_hood_july_29_postmarket.sql` has not been
applied. The profile remains disabled and no order was submitted. A separate
explicit authorization is required for `AUTO_LIVE`.
