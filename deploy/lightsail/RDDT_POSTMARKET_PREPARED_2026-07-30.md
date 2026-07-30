# RDDT POST_MARKET prepared state — 2026-07-30

## Reviewed event

- Issuer: Reddit, Inc. (`RDDT`, CIK `1713445`)
- Period: 2026 Q2
- Official release: after the July 30 market close
- Conference call: `2026-07-30T20:30:00Z`
- Earliest expected release: `2026-07-30T20:08:00Z`
- Timing basis: `HISTORICAL_PATTERN`, high confidence
- Activation safety lead: 7,200 seconds
- Polymarket rule: GAAP diluted EPS strictly greater than `0.97`
- Fallback metric basis: GAAP basic EPS

The issuer schedule is confirmed by:

`https://investor.redditinc.com/news-events/news-releases/news-details/2026/Reddit-to-Announce-Second-Quarter-Results-on-Thursday-July-30-2026/default.aspx`

The timing estimate uses the issuer's two recent SEC acceptances near
16:08:35 ET, not the later conference-call time.

## Sources and parser

The checked-in `RedditGaapDilutedEpsParser` accepts only an unambiguous
current-quarter GAAP result from either of Reddit's stable formats:

- a net-income headline followed by `Diluted EPS of ...`; or
- the explicit `Basic and diluted ... were ..., respectively` pair.

Guidance-only and table-only documents fail closed. Conflicting accepted
patterns are quarantined.

Source paths:

1. always-on SEC-API WebSocket;
2. profile-gated SEC current-filings polling;
3. profile-gated Reddit IR HTML polling;
4. profile-gated BusinessWire RSS polling;
5. SEC Latest observation-only tail.

The official Q1 2026 release replayed as GAAP diluted EPS `1.01`.

## Profile and schedule

- Rule: `rddt-2026q2-gaap-eps-0pt97`
- Scope: `earnings:RDDT:2026Q2`
- Profile: `earnings-rddt-2026q2`
- Schedule: `schedule:earnings-rddt-2026q2`
- Account: `abccbaq`
- Quantity: 100
- YES/NO desired prices: `0.999`
- Tick lifecycle: `0.01 -> 0.001`, at most one reprice
- Preflight: `2026-07-30T17:53:00Z`
- Activation: `2026-07-30T18:08:00Z`
- Deactivation: `2026-07-31T02:00:00Z`

Seed 034 and its read-only verifier passed in staging and production while
the rule remained `SHADOW`, the profile remained `DISABLED`, and the schedule
remained `AUTO_PREFLIGHT`.

## Immutable deployment

- Feature commit: `4309cca`
- Source archive SHA256:
  `38e87a30084b0ce394072bddcb01c5e7dfc3851fa44aa1873a62b17c03eb876e`
- Image:
  `codexpoly@sha256:67fbe6a12dd087986b754c07b9b3d9113a6edf5ea95244fdd906ffbc9ba0f784`
- Image archive SHA256:
  `52df6e25cf976ea6f086deaed938887d4dd97c969e7a3b15c86dc3b51dc8b6ff`

The build passed the secret scan and all 957 tests. Only the staging and
production `earnings-worker` services were recreated. Both used the exact
immutable image with restart count zero. The production SEC stream started
with 29 aggregate watches, of which 28 were earnings watches and one was the
MSTR watch.

The manual authenticated preflight was non-submitting and returned:

```text
ok=true
prepared_count=2
template_count=2
all_presigned=true
executor_execute_called=false
order_submitted=false
maximum_notional=99.00
```

The current 0.01 tick explains the prepared `99.00` notional. The reviewed
desired-price maximum remains `99.90`.

## Production arming

The operator separately authorized the shared worker restart and RDDT
`AUTO_LIVE` transition with global caps `100 / 100 / 1000`.

- Shared `resolution-worker` and `profile-readiness-worker` were recreated on
  the RDDT image with restart count zero.
- The repeated authenticated preflight prepared and pre-signed 2/2 templates
  without submitting an order.
- Guarded live SQL 040 passed before the activation deadline.
- The pre-activation read-only armed verifier passed with the profile still
  disabled.
- At `2026-07-30T18:08:00Z`, the scheduler changed the schedule to `ACTIVE`
  and the profile to `ENABLED`.
- The post-activation RDDT verifier passed with a fresh supervised live
  heartbeat and no validated fact or execution claim.

AAPL and DLB remained safely armed after the restart. AMZN had already
crossed its activation time, so its pre-activation verifier correctly became
inapplicable; the dedicated post-activation verifier confirmed
`ACTIVE/ENABLED`, a fresh live heartbeat, and no fact or claim.

At the first post-activation earnings heartbeat, the SEC WebSocket was
connected and the two active earnings scopes had four public watches, two
SEC-current watches, and two SEC-Latest observation watches. Public and
SEC-current polling were succeeding. The only accumulated source errors were
intermittent timeouts from the observation-only SEC Latest feed; they did not
degrade the independent trading-capable sources.
