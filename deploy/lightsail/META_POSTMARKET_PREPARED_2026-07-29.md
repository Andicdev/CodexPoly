# META POST_MARKET prepared — 2026-07-29

Only the META Q2 2026 event was added. QCOM, MSFT, EBAY, HOOD, SBUX, FED,
and every completed PRE_MARKET profile were left unchanged.

## Reviewed event

- Polymarket market:
  `meta-quarterly-earnings-gaap-eps-07-29-2026-7pt2`
- Resolution metric: GAAP diluted EPS
- Rule: reported value `> 7.20` resolves YES
- Official release: after market close on July 29, 2026
- Estimated publication: `2026-07-29T20:05:00Z`
- Conference call: `2026-07-29T20:30:00Z`

## Source paths

The single META rule has three independent detection paths:

1. persistent SEC-API WebSocket for the META 8-K / Item 2.02 / EX-99.1;
2. profile-gated official Meta IR RSS polling;
3. profile-gated PR Newswire RSS polling.

The title filters require `Meta Reports`, `Second Quarter`, `2026`, and
`Results`. The existing `Meta to Announce ...` item is explicitly rejected.

## Execution profile

- Profile: `earnings-meta-2026q2`
- Account: `abccbaq`
- YES desired price: `0.999`
- NO desired price: `0.999`
- Quantity: `100`
- Lifecycle: `reprice_on_tick_change`
- Tick transition: `0.01 -> 0.001`
- Maximum reprices: `1`
- Prepare from: `2026-07-29T18:00:00Z`
- Expires at: `2026-07-30T02:00:00Z`
- Current profile status: `DISABLED`
- Current schedule mode/state: `AUTO_PREFLIGHT / PENDING`

The reviewed notional is `99.9`, below the aggregate cap `1000`.

## Verification

- The META-only seed applied successfully to staging.
- The read-only staging invariant check passed.
- The same disabled/AUTO_PREFLIGHT seed applied successfully to production.
- The read-only production invariant check passed.
- Production had no META source event, validated fact, execution claim, or
  active order group before preparation.
- A manual authenticated, non-submitting production preflight prepared both
  outcome templates successfully with no errors.
- Only `earnings-worker` was restarted so its persistent SEC stream would
  reload the new rule.
- Sanitizer-first production health markers showed the stream increase from
  `14` to `15` watches, `connected=True`, and `errors=0`.
- Public and SEC-current polling remained inactive while the profile was
  disabled, as required by the profile gate.
- Secret scan passed.
- The complete unit suite passed: `758` tests, `1` skipped.

## Deliberately not applied

`deploy/lightsail/live/022_arm_meta_july_29_postmarket.sql` was reviewed and
tested but not applied. It changes only the META schedule from
`AUTO_PREFLIGHT` to `AUTO_LIVE`; it never enables the profile directly and
still requires fresh authenticated readiness plus a live heartbeat.
