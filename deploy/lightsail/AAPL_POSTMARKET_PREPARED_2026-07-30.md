# AAPL POST_MARKET prepared - 2026-07-30

Only the Apple Q3 2026 earnings market was added. The production profile was
first prepared without live authority and was armed only after a separate
explicit operator authorization.

## Official schedule and market rule

- Apple Investor Relations confirms the Q3 2026 results call for Thursday,
  July 30 at 14:00 PT (21:00 UTC):
  <https://investor.apple.com/investor-relations/default.aspx>
- Apple does not publish the exact release timestamp in advance. The two
  comparable SEC 8-K filings were accepted at 16:30:25 ET for Q3 2025 and
  16:30:41 ET for Q2 2026.
- The catalog therefore stores 20:30 UTC as both the historical estimate and
  earliest signal time.
- Authenticated preflight is scheduled for 18:15 UTC and activation for
  18:30 UTC, two hours before the earliest signal.
- The Polymarket condition is strict: reported GAAP diluted EPS greater than
  `1.89` resolves YES:
  <https://polymarket.com/event/aapl-quarterly-earnings-gaap-eps-07-30-2026-1pt89>

The timing basis is `HISTORICAL_PATTERN` with `HIGH` confidence. Conference
call time is recorded separately and is never substituted for release time.

## Parser and source paths

`AppleGaapDilutedEpsParser` accepts only Apple current-quarter headline forms
that state diluted earnings per share. It rejects unrelated figures and
non-current-quarter text.

The rule has three trading-capable discovery routes:

1. the always-on SEC-API WebSocket;
2. profile-gated official SEC current-filings polling;
3. profile-gated Apple Newsroom Atom polling at
   <https://www.apple.com/newsroom/rss-feed.rss>.

Official SEC Latest polling is enabled as an observation-only route so source
discovery latency can be compared without allowing it to trigger an order.
No unverified press-wire route was added.

Historical replay against Apple's official Q3 2025 release extracted GAAP
diluted EPS `1.57` as expected.

## Execution profile

- Profile: `earnings-aapl-2026q3`
- Account: `abccbaq`
- YES / NO desired price: `0.999`
- Quantity: `100`
- Desired maximum notional: `99.9`
- Runtime maximum order quantity: `200`
- Runtime per-order notional cap: `200`
- Runtime aggregate notional cap: `1000`
- Lifecycle: `reprice_on_tick_change`
- Tick transition: `0.01 -> 0.001`
- Maximum reprices: `1`
- Prepare from: `2026-07-30T18:30:00Z`
- Expires at: `2026-07-31T02:00:00Z`

## Immutable deployment and verification

- Feature commit: `9e095f6`
- Live-cap guard commit: `d7a588d`
- Source archive SHA256:
  `233764c1075dec63c9e6a249621c8832cc2a23a3b82b8e1f5d9123e52139f758`
- Image:
  `codexpoly@sha256:8cc638d6b3943c6f7cd966a254d369ea2ead36e386df473417b0837e80001cdf`
- Image archive SHA256:
  `71ae8553f79eb54e614a7215270afaa409b546fa728ff13b185b494042c01123`

The immutable build passed the repository secret scan and all 949 tests, with
one skipped test.

Seed 032 and the guarded read-only verifier passed in staging and production.
During non-live preparation only the earnings worker was recreated on the new
image. Both earnings-worker instances reported restart count zero, a
connected SEC stream, and zero errors.

The manual authenticated non-submitting production preflight prepared and
pre-signed both outcome templates:

```text
ok=true
prepared_count=2
template_count=2
all_presigned=true
maximum_notional=99.0
order_submitted=false
executor_execute_called=false
```

The preflight maximum is `99.0` because the current `0.01` tick clamps the
desired `0.999` price to `0.99`. The stored desired maximum remains `99.9`;
the normal tick transition permits repricing to `0.999`.

No validated AAPL fact, execution claim, order group, or order was created.

## Current production state

The guarded verifier confirms:

```text
rule=SHADOW
profile=DISABLED
schedule=AUTO_LIVE/PENDING
armed_for_live=true
runtime_caps=200/200/1000
```

After separate explicit authorization, the shared production resolution and
readiness workers were recreated on the same reviewed AAPL image with global
caps `200 / 200 / 1000`. The operator explicitly accepted that these caps
also apply to AMZN and that the shared restart briefly interrupts the common
live path.

The safe-restart guard passed immediately before recreation. Both workers
then reported the exact reviewed image, restart count zero, and running
status. Name-scoped boolean checks confirmed the approved caps in both
containers. Sanitized startup evidence confirmed:

- live resolution heartbeat with supervision and trading enabled;
- readiness worker ready in non-submitting mode;
- no startup error or traceback.

A fresh authenticated non-submitting AAPL preflight after the restart again
prepared and pre-signed two templates with current-tick maximum notional
`99.0`; it did not call executor execution or submit an order.

Migration `038_arm_aapl_july_30_postmarket.sql` was then applied in production.
Its independent read-only verifier required a fresh live resolution heartbeat
and rejected any validated AAPL fact, execution claim, or active order group.
The separately armed AMZN schedule passed its own independent verifier after
the shared worker restart.

The scheduler remains responsible for authenticated readiness at 18:15 UTC
and profile activation at 18:30 UTC. Before that window, public and SEC
polling remain inactive by design while the SEC-API WebSocket remains
connected. Any failed guard must leave the AAPL profile disabled.
