# RIVN POST_MARKET active state — 2026-07-30

## Reviewed event

- Issuer: Rivian Automotive, Inc. (`RIVN`, CIK `1874178`)
- Period: 2026 Q2
- Official release: after the July 30 market close
- Conference call: `2026-07-30T21:00:00Z`
- Earliest expected release: `2026-07-30T20:00:00Z`
- Timing basis: `HISTORICAL_PATTERN`, high confidence
- Polymarket rule: GAAP diluted EPS strictly greater than `-0.78`
- Fallback metric basis: GAAP basic EPS

The issuer schedule is confirmed by:

`https://www.sec.gov/Archives/edgar/data/1874178/000187417826000048/ex-9912q26deliveryproducti.htm`

The timing estimate uses the issuer's Q1 2026 and Q2 2025 SEC
acceptances near 16:00 ET, not the later conference-call time.

## Sources and parser

`RivianGaapDilutedEpsParser` accepts only Rivian's exact GAAP
`basic and diluted` loss-per-share row and selects the current-period
value. A preliminary release containing revenue or cash but no EPS fails
closed. Conflicting exact rows are quarantined.

Source paths:

1. always-on SEC-API WebSocket;
2. profile-gated SEC current-filings polling;
3. profile-gated Rivian newsroom HTML polling;
4. profile-gated BusinessWire RSS polling;
5. SEC Latest observation-only tail.

The official Q1 2026 release replayed as GAAP EPS `-0.33`.

## Profile and schedule

- Rule: `rivn-2026q2-gaap-eps-neg0pt78`
- Scope: `earnings:RIVN:2026Q2`
- Profile: `earnings-rivn-2026q2`
- Schedule: `schedule:earnings-rivn-2026q2`
- Account: `abccbaq`
- Quantity: 100
- YES/NO desired prices: `0.999`
- Tick lifecycle: `0.01 -> 0.001`, at most one reprice
- Preflight: `2026-07-30T18:30:00Z`
- Activation: `2026-07-30T18:45:00Z`
- Deactivation: `2026-07-31T02:00:00Z`

Preparation began after the standard two-hour activation lead had
already passed. The seed therefore remained `AUTO_PREFLIGHT` and required
separate operator acceptance of a reduced 4,500-second safety lead. The
operator explicitly accepted that late activation before live arming.

## Verification and deployment

- Parser/profile commit: `cf42b5d`
- Guarded live-transition commit: `391e3e1`
- Source archive SHA256:
  `0c25608f219d50cc4be2af46e8c4f07cbd30b3fbf33c200dde7b0b2807bbe7d7`
- Image:
  `codexpoly@sha256:139b48a4f939e11ae04a348e234375bacdd8b3a4fcbb5de7da68e1ded28bea9c`
- Image archive SHA256:
  `e624f8adedafa332aa21ea9175a614dfd085d7d481a06242ad110872f94665e7`

The local and immutable-image builds passed the secret scan and all 961
tests. Staging and production earnings workers were recreated first.
Production earnings started with 30 aggregate SEC watches: 29 earnings
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

Guarded live SQL 041 passed at `2026-07-30T18:37:23Z`. Before activation,
RIVN was `READY/DISABLED`, the supervised live heartbeat was fresh, and
there was no fact or execution claim. The restart-preservation verifier
also confirmed that AMZN, AAPL, DLB and RDDT remained `ACTIVE/ENABLED`.

At `2026-07-30T18:45:00Z`, the scheduler moved RIVN to
`ACTIVE/ENABLED`. The post-activation verifier passed with a fresh
supervised live heartbeat and no premature execution claim.

The next earnings heartbeat confirmed that profile-gated source coverage
expanded from four to five active scopes: public watches increased from
seven to nine, and SEC current and SEC Latest watches increased from four
to five. Public and SEC-current success counters continued increasing.
The cumulative error count included intermittent PRNewswire and
observation-only SEC Latest timeouts; independent trading-capable sources
remained active.
