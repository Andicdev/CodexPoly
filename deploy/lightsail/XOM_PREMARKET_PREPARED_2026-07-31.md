# XOM PRE_MARKET preparation — 2026-07-31

Status: immutable image deployed to production; XOM is safely armed as
`AUTO_LIVE / PENDING` with its execution profile still `DISABLED`.

## Reviewed event

- Issuer: ExxonMobil Holdings Corporation (`XOM`)
- Current SEC CIK: `2115436`
- Predecessor SEC CIK: `34088`
- Period: 2026 Q2, ended June 30, 2026
- Official release: `2026-07-31T10:30:00Z` (`05:30 CT`)
- Conference call: `2026-07-31T13:30:00Z` (`08:30 CT`)
- Polymarket rule: primary non-GAAP EPS strictly greater than `3.66`
- Metric: `Earnings Excluding Identified Items Per Common Share`
- Condition:
  `0x4f47cfcf38650017dfcbf87a05776eb9692bdfab37d8bd8bcdba8733c7eb0fcd`

The exact release time is stated in the issuer announcement:

`https://investor.exxonmobil.com/company-information/press-releases/detail/1207/exxonmobil-to-release-second-quarter-2026-financial-results`

The separate call evidence is:

`https://investor.exxonmobil.com/news-events/ir-calendar/detail/20260731-2q-2026-earnings-call`

ExxonMobil completed its redomiciliation on July 1, 2026. The new publicly
traded parent files under CIK `2115436`; continuing to watch only predecessor
CIK `34088` would miss the current filing.

## Parser contract

`ExxonEarningsExcludingItemsEpsParser` accepts only:

1. the exact results-summary row
   `Earnings Excluding Identified Items Per Common Share (non-GAAP)`; or
2. the matching prose form
   `Earnings excluding identified items were ..., or $X per share`.

It does not accept GAAP EPS or
`Earnings Excluding Identified Items and Estimated Timing Effects`.
Conflicting exact values are quarantined.

The official Q1 2026 IR HTML replay selected `1.16`, not the alternative
`2.09` value that also excluded estimated timing effects.

## Source race

1. ExxonMobil investor-relations RSS, profile-gated and replay-verified:
   `https://investor.exxonmobil.com/company-information/press-releases/rss`
2. BusinessWire RSS, profile-gated configured fallback
3. SEC-API WebSocket, always connected
4. SEC current-filings polling, profile-gated
5. SEC Latest Filings, observation-only

The official Q1 RSS item was timestamped `06:30:00 ET`; its SEC filing was
accepted at `06:31:52 ET`. This makes the issuer RSS the currently reviewed
latency leader by approximately 112 seconds. BusinessWire is retained because
the issuer explicitly says the release will be issued through BusinessWire,
but the generic category feed is not counted as an independently
replay-verified route.

## Execution schedule

- Rule: `xom-2026q2-nongaap-eps-3pt66`
- Scope: `earnings:XOM:2026Q2`
- Profile: `earnings-xom-2026q2`
- Schedule: `schedule:earnings-xom-2026q2`
- Account: `abccbaq`
- Quantity: 100
- YES/NO desired prices: `0.999`
- Tick lifecycle: `0.01 -> 0.001`, one reprice
- Preflight: `2026-07-31T08:15:00Z`
- Activation: `2026-07-31T08:30:00Z`
- Earliest signal: `2026-07-31T10:30:00Z`
- Deactivation: `2026-07-31T14:00:00Z`
- Timing contract: `OFFICIAL_EXACT`, version 1, 7,200-second safety lead
- Seed mode/status: `AUTO_PREFLIGHT / PENDING`, profile `DISABLED`
- Armed mode/status: `AUTO_LIVE / PENDING`, profile `DISABLED`

The seed itself cannot enable live trading. The separately authorized
immutable-image rollout and `AUTO_LIVE` transition are complete.
Authenticated preflight and scheduler-owned activation remain pending at
their time boundaries.

## Guarded live artifacts

The following guarded artifacts were applied after explicit operator
authorization:

- `live/044_arm_xom_july_31_premarket.sql` changes only the reviewed XOM
  schedule from `AUTO_PREFLIGHT` to `AUTO_LIVE`. It requires a fresh fully-live
  resolution heartbeat, a disabled profile, the exact market/rule/timing
  contract, a clean scope, and caps `100 / 100 / 1000`.
- `checks/verify_xom_july_31_auto_live_armed.sql` verifies the safe armed state
  before activation.
- `checks/verify_xom_july_31_preflight_ready.sql` verifies fresh authenticated
  readiness during the 08:15--08:30 UTC preflight interval.
- `checks/verify_xom_july_31_live_active.sql` verifies scheduler-owned
  activation between 08:30 UTC and the 10:30 UTC release.

## Production rollout

- Application commit: `018896a`.
- Source archive SHA256:
  `d08277606b703ff1f2eee65f06ca5d49fc8f682a337cd32c1f2d93954921e4a5`.
- Immutable image:
  `codexpoly@sha256:f08d723b87ce274e65e4595b7b6c2c57db4176b4042f75a67464ce5cd0aed23d`.
- Image archive SHA256:
  `b920b181131b5da3cc7a17c92b12ddc8efca0be08a0572f5c3623a170318154e`.
- OCI revision: `018896a`.

The image was built from the clean Git archive in rootless Docker. The build
repeated the secret scan and all `999` tests. The exact exported image was
then checksum-recorded and loaded into rootful production Docker.

Recoverable Compose copies were saved as:

- `compose.before-018896a.yml`;
- `compose.trading.before-018896a.yml`.

All five production application workers were recreated on the immutable
image. PostgreSQL was not restarted. The approved runtime controls remain:

- live resolution and order supervision enabled;
- scheduler automatic live activation enabled;
- quantity, per-order notional, and aggregate caps `100 / 100 / 1000`;
- authenticated readiness remains non-submitting.

Production seed 037 and its disabled-profile verifier passed. The new runtime
reported a connected SEC WebSocket with `32` aggregate watches, a fresh
fully-live resolution heartbeat, and no managed profile or startup error.
Guarded arming and its read-only verifier then passed:

```text
schedule=AUTO_LIVE/PENDING
profile=DISABLED
fact_candidates=0
execution_claims=0
orders_submitted=0
```

Authenticated preflight remains scheduler-owned at 08:15 UTC. Activation
remains scheduler-owned at 08:30 UTC and must fail closed unless readiness is
fresh. A thread heartbeat monitors both boundaries and is removed after the
final active-state verification.
