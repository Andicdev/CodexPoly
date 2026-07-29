# MSFT POST_MARKET prepared — 2026-07-29

Only the Microsoft FY2026 Q4 event was added. META, QCOM, EBAY, HOOD, SBUX,
FED, and every completed PRE_MARKET profile were left unchanged.

## Reviewed event

- Polymarket market:
  `msft-quarterly-earnings-gaap-eps-07-29-2026-4pt21`
- Resolution metric: GAAP diluted EPS
- Rule: reported value `> 4.21` resolves YES
- Official release: after market close on July 29, 2026
- Estimated publication: after `2026-07-29T20:00:00Z`
- Conference call: `2026-07-29T21:30:00Z`

Microsoft's official announcement does not promise an exact publication
minute. The prior FY2026 Q3 Investor RSS item was timestamped at approximately
`20:12 UTC`, so the profile opens well before the expected release.

## Source paths

The single MSFT rule has three independent detection paths:

1. persistent SEC-API WebSocket for the MSFT 8-K / Item 2.02 / EX-99.1;
2. profile-gated official SEC current-filings polling;
3. profile-gated Microsoft Source Investor Relations RSS polling.

The official RSS filter requires `Microsoft`, `fourth quarter`, and `results`.
The separate earnings release-date announcement cannot match this filter.

## Execution profile

- Profile: `earnings-msft-2026q4`
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

- The MSFT-only seed applied successfully to staging.
- The read-only staging invariant check passed.
- The same disabled/AUTO_PREFLIGHT seed applied successfully to production.
- The read-only production invariant check passed.
- Production had no MSFT source event, validated fact, execution claim, or
  active order group before preparation.
- A manual authenticated, non-submitting production preflight prepared both
  outcome templates successfully with no errors.
- Only `earnings-worker` was restarted so its persistent SEC stream would
  reload the new rule.
- Sanitizer-first production health markers showed the stream increase from
  `15` to `16` watches, `connected=True`, and `errors=0`.
- A signal visible immediately before restart belonged to PAG. A read-only
  scope check confirmed that both MSFT and META still had zero validated facts
  and zero execution claims.
- Secret scan passed.
- The complete unit suite passed: `765` tests, `1` skipped.

## Deliberately not applied

`deploy/lightsail/live/023_arm_msft_july_29_postmarket.sql` was reviewed and
tested but not applied. It changes only the MSFT schedule from
`AUTO_PREFLIGHT` to `AUTO_LIVE`; it never enables the profile directly and
still requires fresh authenticated readiness plus a live heartbeat.
