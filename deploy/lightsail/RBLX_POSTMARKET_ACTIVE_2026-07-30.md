# RBLX POST_MARKET active state — 2026-07-30

## Reviewed event

- Issuer: Roblox Corporation (`RBLX`, CIK `1315098`)
- Period: 2026 Q2
- Official release: after the July 30 market close
- Conference call: `2026-07-30T20:30:00Z`
- Earliest expected release: `2026-07-30T20:00:00Z`
- Timing basis: `HISTORICAL_PATTERN`, high confidence
- Polymarket rule: GAAP diluted EPS strictly greater than `-0.33`
- Fallback metric basis: GAAP basic EPS

The official issuer schedule is:

`https://ir.roblox.com/news/news-details/2026/Roblox-to-Report-Second-Quarter-2026-Financial-Results-on-July-30-2026/default.aspx`

The release estimate uses the issuer's Q1 2026 SEC acceptance at
`2026-04-30T20:08:45Z`, rather than the later conference-call time.

## Sources and parser

`RobloxGaapDilutedEpsParser` accepts only Roblox's exact GAAP
`Net loss per share attributable to common stockholders, basic and diluted`
row and selects the current-period value. Releases without that row fail
closed, and conflicting exact rows are quarantined.

Source paths:

1. always-on SEC-API WebSocket;
2. profile-gated SEC current-filings polling;
3. profile-gated Roblox investor-relations HTML polling;
4. profile-gated BusinessWire RSS polling;
5. SEC Latest observation-only tail.

The official Q1 2026 release replayed as GAAP EPS `-0.35`.

## Profile and schedule

- Rule: `rblx-2026q2-gaap-eps-neg0pt33`
- Scope: `earnings:RBLX:2026Q2`
- Profile: `earnings-rblx-2026q2`
- Schedule: `schedule:earnings-rblx-2026q2`
- Account: `abccbaq`
- Quantity: 100
- YES/NO desired prices: `0.999`
- Tick lifecycle: `0.01 -> 0.001`, at most one reprice
- Preflight: `2026-07-30T19:15:00Z`
- Activation: `2026-07-30T19:20:00Z`
- Deactivation: `2026-07-31T02:00:00Z`

Preparation began after the standard two-hour activation lead had
already passed. The seed therefore remained `AUTO_PREFLIGHT` and required
separate operator acceptance of a reduced 2,400-second safety lead. The
operator explicitly accepted the late activation before live arming.

## Verification and deployment

- Parser/profile commit: `921558e`
- Guarded live-transition commit: `26ae1d5`
- Source archive SHA256:
  `4859d219491157da25eb9446c48611f23edbbd19a82a9a08551a011c0bac0938`
- Image:
  `codexpoly@sha256:14876823b5d2b1045fb5c7dbdf4421828e57b6b7c552662132344815a35d5015`
- Image archive SHA256:
  `3557a0b317c59269d5c86985fcb0d90d6f98139812775906952ee915af24c783`

The local and immutable-image builds passed the secret scan and all 965
tests. Staging and production earnings workers were recreated first.
Production earnings started with 31 aggregate SEC watches: 30 earnings
watches plus the MSTR watch.

The shared production resolution and readiness workers were then recreated
on the same image with global caps `100 / 100 / 1000`; both reported restart
count zero. The repeated authenticated preflight returned:

```text
ok=true
prepared_count=2
template_count=2
all_presigned=true
executor_execute_called=false
order_submitted=false
maximum_notional=99.00
```

Guarded live SQL 042 passed at `2026-07-30T19:09:07Z`. A current-state
restart-preservation verifier confirmed that AMZN, AAPL, DLB, RDDT and RIVN
remained `ACTIVE/ENABLED`; RBLX remained pre-activation
`PENDING/DISABLED`, with a fresh supervised live heartbeat, no schedule
errors and no execution claim.

After `2026-07-30T19:15:00Z`, authenticated readiness moved RBLX to
`READY` while the profile remained `DISABLED`. At
`2026-07-30T19:20:00Z`, the scheduler moved it to `ACTIVE/ENABLED`.
Both guarded read-only verifiers passed, and no premature execution claim
or order was present.

The first post-activation earnings heartbeat confirmed that profile-gated
source coverage expanded from five to six active scopes: public watches
increased from nine to eleven, and SEC current and SEC Latest watches
increased from five to six. The SEC WebSocket remained connected.
Intermittent PRNewswire and observation-only SEC Latest timeouts continued,
but public and SEC-current success counters increased and independent
trading-capable sources remained active.
