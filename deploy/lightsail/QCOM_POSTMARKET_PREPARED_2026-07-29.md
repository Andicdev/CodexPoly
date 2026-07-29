# QCOM POST_MARKET prepared — 2026-07-29

Only the Qualcomm fiscal Q3 2026 event was added. META, MSFT, EBAY, HOOD,
SBUX, FED, and completed PRE_MARKET profiles were left unchanged.

## Reviewed event

- Polymarket market:
  `qcom-quarterly-earnings-nongaap-eps-07-29-2026-2pt23`
- Resolution metric: non-GAAP diluted EPS
- Rule: reported value `> 2.23` resolves YES
- Official release: after market close on July 29, 2026
- Estimated publication: approximately `2026-07-29T20:05:00Z`
- Conference call: `2026-07-29T20:45:00Z`

## Source paths

The QCOM rule has three independent detection paths:

1. persistent SEC-API WebSocket for the QCOM 8-K / Item 2.02 / EX-99.1;
2. profile-gated official SEC current-filings polling;
3. profile-gated HEAD polling of Qualcomm's predictable official earnings
   PDF on Q4 CDN.

The Q3 direct-document URL currently returns `404`, which is the safe expected
state before publication. Historical Q1, Q2, and Q3 files use the same stable
path structure. The current parser was tested against Qualcomm's real Q2 FY26
earnings PDF and accepted non-GAAP diluted EPS `2.65`.

Qualcomm's press-release RSS is not used for resolution because it publishes a
short "earnings release available" notice without the EPS value. The official
PDF is the useful company source.

## Execution profile

- Profile: `earnings-qcom-2026q3`
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

The reviewed notional is `99.9`, below the aggregate cap `1000`. A separate
explicit authorization is required before changing the schedule to
`AUTO_LIVE`.

## Verification

- The QCOM-only seed applied successfully to staging.
- The read-only staging invariant check passed.
- The same disabled/AUTO_PREFLIGHT seed applied successfully to production.
- The read-only production invariant check passed.
- Production had no QCOM validated fact, execution claim, or active order
  group before preparation.
- A manual authenticated, non-submitting production preflight prepared and
  pre-signed both outcome templates.
- The preflight reported `order_submitted=false` and
  `executor_execute_called=false`.
- Preparing both alternatives used aggregate notional `199.8`; only one
  resolved outcome can be selected, so the per-event trading exposure remains
  `99.9`, and both values are below the aggregate cap `1000`.
- Only `earnings-worker` was restarted so the persistent SEC stream would
  reload the new rule.
- Sanitizer-first production health markers showed the stream increase from
  `16` to `17` total watches, `connected=True`, and `errors=0`.
- Public and SEC-current polling correctly remained inactive while the QCOM
  profile was disabled.
- Secret scan passed.
- The complete unit suite passed: `773` tests, `1` skipped.

## Deliberately not applied

The production QCOM schedule remains `AUTO_PREFLIGHT / PENDING` and the
profile remains `DISABLED`. The guarded
`deploy/lightsail/live/024_arm_qcom_july_29_postmarket.sql` migration is
prepared but has not been applied.
