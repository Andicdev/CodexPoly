# DLB POST_MARKET prepared - 2026-07-30

Only the Dolby Laboratories Q3 fiscal 2026 earnings market was added. The
production rule remains `SHADOW`, the execution profile remains `DISABLED`,
and the schedule remains `AUTO_PREFLIGHT` pending separate live authority.

## Official schedule and market rule

- Dolby Investor Relations confirms results after regular trading closes on
  Thursday, July 30, 2026, and a 14:00 PT / 17:00 ET call:
  <https://investor.dolby.com/news-events/financial-news/news-details/2026/Dolby-Laboratories-Announces-Conference-Call-and-Webcast-for-Q3-Fiscal-2026-Financial-Results/default.aspx>
- Comparable Dolby SEC filings were accepted near 16:15 ET. The catalog
  therefore stores `20:15 UTC` as the historical release estimate and
  earliest signal time, separately from the `21:00 UTC` call.
- Authenticated preflight is scheduled for `18:00 UTC` and activation for
  `18:15 UTC`, two hours before the earliest signal.
- The Polymarket condition is strict: reported non-GAAP diluted EPS greater
  than `0.67` resolves YES:
  <https://polymarket.com/event/dlb-quarterly-earnings-nongaap-eps-07-30-2026-0pt67>

The timing basis is `HISTORICAL_PATTERN` with `HIGH` confidence.

## Parser and source paths

`DolbyNonGaapDilutedEpsParser` accepts only Dolby's current-quarter headline
form:

```text
On a non-GAAP basis, third quarter net income was ...,
or $X per diluted share.
```

It fails closed on GAAP EPS, guidance, reconciliation tables, and conflicting
current-quarter headline values. Historical replay against Dolby's official
Q3 fiscal 2025 release extracted non-GAAP diluted EPS `0.78`; it did not
capture the nearby GAAP EPS `0.48`.

The rule has four trading-capable discovery routes:

1. always-on SEC-API WebSocket;
2. profile-gated official SEC current-filings polling;
3. profile-gated Dolby Investor Relations HTML-listing polling;
4. profile-gated PRNewswire RSS polling.

SEC Latest remains an observation-only source for source-discovery latency
comparison.

## Execution profile

- Profile: `earnings-dlb-2026q3`
- Account: `abccbaq`
- YES / NO desired price: `0.999`
- Quantity: `100`
- Desired maximum notional: `99.9`
- Reviewed runtime caps: `200 / 200 / 1000`
- Lifecycle: `reprice_on_tick_change`
- Tick transition: `0.01 -> 0.001`
- Maximum reprices: `1`
- Prepare from: `2026-07-30T18:15:00Z`
- Expires at: `2026-07-31T02:00:00Z`

## Immutable deployment and verification

- Feature commit: `c68035d`
- Source archive SHA256:
  `5f5dd878c1c2f26b1d41c33066de47bf74f845909760fcf2de0c961c29078ba1`
- Image:
  `codexpoly@sha256:f6fcf284d2787e5fd110035fc6c049a58f6544290fe0a01548bdbd6c7720caa5`
- Tagged image archive SHA256:
  `4ba365c1755a6dc012800b09b7e849576f8ce9d746e95e6bbf3d52b95d866e14`

The local and immutable image builds passed the secret scan and all 953
tests, with one skipped test. Historical network replay also passed.

Seed 033 and the independent read-only verifier passed in staging and
production. Only each environment's earnings worker was recreated. Both use
the exact immutable image, have restart count zero, and report a connected
SEC stream with zero errors. Public, SEC-current, and SEC-Latest polling stay
inactive while the DLB execution profile is disabled.

The manual authenticated, non-submitting production preflight returned:

```text
ok=true
prepared_count=2
template_count=2
all_presigned=true
maximum_notional=99.9
order_submitted=false
executor_execute_called=false
```

No validated DLB fact, execution claim, order group, or order was created.

## Remaining live gate

Production resolution and readiness workers intentionally remain on the
previous reviewed AAPL image. A separate operator authorization is required
to recreate those two shared workers on the DLB image with global caps
`200 / 200 / 1000`, repeat authenticated preflight, and apply guarded
migration `039_arm_dlb_july_30_postmarket.sql`.

That migration can only change the DLB schedule to `AUTO_LIVE`; scheduler
readiness and activation remain responsible for keeping the execution profile
disabled unless all guards pass.
