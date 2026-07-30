# AMZN POST_MARKET prepared — 2026-07-30

Only the Amazon Q2 2026 earnings market was added. The production schedule
was armed only after separate operator authorization.

## Official schedule and market rule

- Amazon confirmed Q2 2026 results for Thursday, July 30, with the conference
  call at 17:00 EDT (21:00 UTC).
- The issuer did not state the exact release timestamp. Amazon's prior
  quarterly result was published at 16:01 EDT, so the catalog stores 20:01 UTC
  as a historical estimate and 20:00 UTC as the earliest signal floor.
- The activation time is 18:00 UTC, two hours before that release floor.
- The Polymarket condition is strict: reported GAAP diluted EPS greater than
  `1.82` resolves YES.

The timing basis is `HISTORICAL_PATTERN` with `MEDIUM` confidence. Conference
call time is recorded separately and is never used as the release time.

## Parser and source paths

`AmazonGaapDilutedEpsParser` accepts only the current-quarter Amazon headline
that reports net income or loss and the corresponding diluted-share amount.
An unsigned value following a reported net loss is normalized to a negative
EPS value. Guidance, conference-call announcements, and unrelated quarterly
values are rejected.

The rule has four trading-capable discovery routes:

1. the always-on SEC-API WebSocket;
2. profile-gated official SEC current-filings polling;
3. profile-gated Amazon Investor Relations RSS polling;
4. profile-gated Business Wire RSS polling.

Official SEC Latest polling is also enabled as an observation-only route so
source-discovery latency can be compared without allowing it to trigger an
order.

Historical replay against Amazon's official Q2 2025 result extracted GAAP
diluted EPS `1.68` as expected.

## Execution profile

- Profile: `earnings-amzn-2026q2`
- Account: `abccbaq`
- YES / NO desired price: `0.999`
- Quantity: `100`
- Reviewed maximum notional: `99.9`
- Aggregate cap: `1000`
- Lifecycle: `reprice_on_tick_change`
- Tick transition: `0.01 -> 0.001`
- Maximum reprices: `1`
- Prepare from: `2026-07-30T18:00:00Z`
- Expires at: `2026-07-31T02:00:00Z`

## Immutable deployment and verification

- Feature commit: `17646ad`
- Source archive SHA256:
  `9372052c17f101f413d429f1287b19f78fd13b14dbccb73440546eebe7dcb072`
- Image:
  `codexpoly@sha256:2ec42dbc6f6f21183cb73f5b0063fb72df089535bc29193a3a7f0a04694ded27`
- Image archive SHA256:
  `b50e6b2c0a9ccab89226cc908e5b2277e7c2b61f0255111c96e21ca98a9f8445`

The immutable build passed the repository secret scan and all 937 tests, with
one skipped test.

Seed 031 and the guarded read-only verifier passed in staging and production.
Only the earnings worker was recreated on the new image. Its restart count
remained zero, the SEC stream connected, and the AMZN polling routes remained
inactive because the execution profile is disabled.

The manual authenticated non-submitting preflight prepared and pre-signed both
outcome templates:

```text
ok=true
prepared_count=2
template_count=2
all_presigned=true
maximum_notional=99.9
order_submitted=false
executor_execute_called=false
```

No validated AMZN fact, execution claim, order group, or order was created.

## Live arming

After separate explicit authorization with limits `100 / 100 / 1000`,
migration `037_arm_amzn_july_30_postmarket.sql` was applied in production.
Its immediate read-only armed verifier passed and confirmed:

```text
rule=SHADOW
profile=DISABLED
schedule=AUTO_LIVE/PENDING
armed_for_live=true
```

The armed verifier also confirmed a fresh live resolution heartbeat with
supervision and trading enabled, a valid timing contract, and no AMZN fact,
execution claim, or active order group. No order was submitted by the arming
migration.

The scheduler remains responsible for a fresh authenticated preflight at
17:45 UTC and profile activation at 18:00 UTC. Any failed readiness or
activation guard must leave the profile disabled.
