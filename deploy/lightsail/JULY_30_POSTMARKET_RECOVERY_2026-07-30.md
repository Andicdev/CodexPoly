# July 30 post-market earnings recovery — 2026-07-30

Status: production hotfix deployed; AMZN/AAPL/DLB remained completed; RDDT
and RBLX were recovered correctly through the normal live resolution path.
RIVN reached execution, but parser version `1` selected a year-to-date column
and produced an incorrect `NO` decision.

## Incident

The observation-only SEC Latest source won the source race for several
filings. It persisted an `OBSERVED` fact and marked the shared source event
`PARSED`. The executable SEC Current and SEC-API WebSocket transports then
encountered the same transport-neutral event key and returned
`already_parsed`, so no executable signal was emitted.

This was a source-event idempotency bug, not parsing or execution latency.
The shared event key is intentionally transport-neutral and remains
unchanged.

RBLX also exposed a separate parser defect. The official SEC exhibit placed
Unicode zero-width formatting marks inside the exact diluted-EPS label. The
old normalizer retained those marks and returned
`roblox_gaap_diluted_eps_row_not_found`.

RIVN exposed another independent parser defect. Its Q2 statement presents
four GAAP EPS values in this order:

1. prior-year three-month EPS;
2. current-year three-month EPS;
3. prior-year six-month EPS;
4. current-year six-month EPS.

Parser version `1` selected the last value, `-0.97`, which is the current
six-month year-to-date result. The market requires the current quarter,
which is the second value, `-0.63`. The correct rule result is therefore
`-0.63 > -0.78`, or `YES`.

## Fix

- An executable transport encountering a terminal `PARSED` event now
  atomically promotes its `OBSERVED` fact to `VALIDATED` and emits the normal
  resolution signal without fetching or parsing the document again.
- The race in which an executable parser reaches an already-persisted
  observation fact is handled by the same promotion primitive.
- Unicode format marks used by the RBLX exhibit are removed during common
  text normalization.
- The RBLX parser audit version is `2`.
- A subsequent local RIVN correction selects the second value from the exact
  basic-and-diluted GAAP EPS row. Its audit version is `3`; a four-column Q2
  regression fixture prevents the quarterly/YTD confusion from recurring,
  and an unknown multi-period header layout now fails closed without a fact.
  This correction was not part of the immutable production image documented
  below and requires a separate deployment.
- A one-shot guarded production retry changed only the reviewed RBLX SEC
  event from `NO_MATCH` to retryable `ERROR`. It refused to run if a fact,
  execution claim, inactive profile, different accession, different source
  URL, or different prior parser error was present.

Commits:

- `6e09928` — executable promotion after observation;
- `b3fb9b6` — Unicode normalization regression fix;
- `5df005b` — RBLX parser version, guarded retry, and production checks.

Verification:

- local secret scan passed;
- local suite: `968` tests passed, `1` skipped;
- immutable-image secret scan passed;
- immutable-image suite: `968` tests passed.

The later, not-yet-deployed RIVN parser-v2 correction passes the local secret
scan and the complete suite of `969` tests with `1` skipped.

## Immutable deployment

- Source archive SHA256:
  `6c8de4642816d742cd170eac82a2ed7f2bb09d1e364966b828a633794b7372b6`
- Image:
  `codexpoly@sha256:87d8e03fff06237abe5fea3be7a59bba6caf749d51fcf766ba39f46e1aef5eea`
- Streamed Docker archive SHA256:
  `5c5fede2f51ef222be2e8cc7174cc5a1291cab31c1d01c6b074b16b892e17690`
- OCI revision: `5df005b`

Only the production `earnings-worker` was recreated. Resolution, readiness,
scheduler, and notification workers were not restarted. A second
earnings-only recreation cleared the process-local completed-accession cache
after the guarded RBLX retry. The final earnings worker reports restart count
zero on the reviewed image.

The final heartbeat has:

- SEC-API WebSocket connected with `31` aggregate watches;
- no active or tail earnings scopes;
- public, SEC Current, and SEC Latest profile-gated polling stopped;
- no new startup or processing failure.

The cumulative source error counter includes the known RBLX IR endpoint
failures and earlier observation-only SEC Latest timeouts. Those paths are
inactive after completion and did not block the independent SEC recovery.

## Results

The earlier successful paths were preserved:

| Ticker | Provider | Fact | Rule | Outcome | Result |
|---|---|---:|---:|---|---|
| AMZN | official IR | `5.75` | `> 1.82` | YES | CLOB response about `58 ms` after signal |
| AAPL | official source | `2.02` | `> 1.89` | YES | initial order plus reviewed tick repricing |
| DLB | PRNewswire | `0.69` | `> 0.67` | YES | live execution completed |

Recovered SEC paths and the RIVN parser incident:

| Ticker | First stored SEC result | Recovery signal | Persisted fact | Correct fact | Persisted outcome | Correct outcome |
|---|---|---|---:|---:|---|---|
| RIVN | SEC Latest `OBSERVED` | `2026-07-30T21:11:14.564Z` | `-0.97` (six-month YTD) | `-0.63` (quarter) | NO | YES |
| RDDT | SEC Latest `OBSERVED` | `2026-07-30T21:11:14.581Z` | `1.25` | `1.25` | YES | YES |
| RBLX | SEC `NO_MATCH` | `2026-07-30T21:12:38.673Z` | `-0.26` | `-0.26` | YES | YES |

All three scopes have exactly one persisted validated fact, one executed
outcome claim, and one expired opposite-outcome claim. For RDDT and RBLX
those directions are correct. For RIVN these records preserve the incorrect
parser-version-`1` decision and must not be interpreted as a correct market
outcome. The live resolution worker detached all three profiles after
execution.

Order audit:

- RDDT has one live `100 YES @ 0.999` order.
- RBLX has one live `100 YES @ 0.999` order.
- RIVN has no remaining live order. The explicitly accepted submit-first
  overlap risk materialized: both the original `100 NO` order (claim
  effective price `0.99`) and the `100 NO @ 0.999` replacement are recorded
  filled. The effective filled quantity is therefore `200`, not the target
  `100`. Both fills are in the wrong direction because the correct market
  outcome is `YES`.
- The RIVN order group is `FAILED` after late reconciliation even though both
  fills are persisted and no live order remains. This is a lifecycle/audit
  anomaly and a separate follow-up item; it is not a lost or open order.

The guarded verifier
`checks/verify_july_30_postmarket_hotfix_results.sql` confirms the exact
persisted incident state, claim pairs, RDDT/RBLX live orders, RIVN double
fill, the absence of a live RIVN order, and the fresh supervised live
heartbeat. Its RIVN predicates intentionally describe the historical wrong
fact and wrong-direction execution; they are not correctness assertions.

## Follow-up

1. Require period-aware fixtures for earnings tables that contain both
   quarterly and year-to-date columns. Parser review must identify the exact
   header/value mapping rather than selecting a value by row position alone.
2. Change submit-first repricing to cap the replacement at the confirmed
   remaining quantity whenever the initial order can be inspected without
   delaying first submission.
3. Treat a fully filled source/replacement pair as a terminal overfill audit
   state rather than a generic failed group.
4. Add parser-version-aware retry semantics for terminal `NO_MATCH` events,
   removing the need for a one-shot guarded SQL retry after future parser
   corrections.
5. Keep SEC Latest observation-only until source-race telemetry is reviewed;
   the promotion fix prevents it from blocking executable transports.
