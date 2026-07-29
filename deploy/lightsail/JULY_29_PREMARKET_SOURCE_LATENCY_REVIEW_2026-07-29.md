# July 29 PRE_MARKET source-latency review

## Scope

This checkpoint covers the production block:

- SOFI
- PG
- HUM
- WING
- ARCC
- IART
- GRMN
- CBRE
- PAG

The production database was inspected read-only after all nine companies had
published. No profile, order, source event, fact, or journal row was changed.
The reusable query is
`checks/diagnose_july_29_source_latency.sql`.

## Outcome

Five profiles produced a validated fact and submitted one order:

| Ticker | Winning provider | Source discovery | Parse | Decision | Exchange | Hot path |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| IART | GlobeNewswire | 145.116 s | 5.025 s | 77 ms | 50 ms | 126 ms |
| HUM | company IR | 234.939 s | 426 ms | 70 ms | 48 ms | 118 ms |
| GRMN | company IR | 310.130 s | 1.511 s | 36 ms | 46 ms | 82 ms |
| PG | SEC | 60.769 s | 2.025 s | 120 ms | 62 ms | 182 ms |
| SOFI | SEC | 51.910 s | 2.093 s | 348 ms | 55 ms | 403 ms |

`Hot path` is fact detection through the accepted exchange response. It does
not include tick-size repricing.

No order filled. HUM, IART, and SOFI reached `0.999`; PG and GRMN remained at
`0.99` under the pre-fix supervisor. The submit-first supervisor fix was
deployed only after these events.

Four profiles received a document but produced no validated fact:

| Ticker | Fastest observed provider | Discovery | Parser result |
| --- | --- | ---: | --- |
| CBRE | company IR | 7.416 s | `cbre_gaap_eps_not_found` |
| WING | company IR | 3.927 s | `wingstop_gaap_eps_not_found` |
| PAG | PR Newswire | 61.407 s | `conflicting_penske_automotive_gaap_eps_values` |
| ARCC | SEC catch-up | 9 h 31 m 45 s | `conflicting_ares_capital_core_eps_values` |

ARCC is not a valid live-latency sample: the filing was already historical
when the profile-gated SEC current-filings path collected it.

## Provider comparison

The historical SEC rows were written before the `acceptanceDateTime`
timezone correction in image `cb5e5a`. Their stored clock fields were
reinterpreted as US Eastern wall time for this report.

| Ticker | SEC discovery | IR discovery | Wire discovery |
| --- | ---: | ---: | ---: |
| CBRE | 77.886 s | 7.416 s | — |
| GRMN | 67.419 s | 310.130 s | 423.910 s |
| HUM | 47.018 s | 234.939 s | — |
| IART | 49.333 s | 153.222 s | 145.116 s |
| PG | 60.769 s | — | — |
| SOFI | 51.910 s | — | — |
| WING | 50.215 s | 3.927 s | 62.315 s |

The current schema identifies all SEC candidates as provider `sec` but does
not persist whether SEC WebSocket or SEC current-filings polling won. That is
an instrumentation gap and prevents a valid latency comparison between the
two SEC transports.

## Findings

1. The prepared execution path is not the primary bottleneck. It completed in
   82–403 ms after fact detection.
2. Official company IR can be materially faster than SEC. CBRE and WING were
   visible in under eight seconds, but the ticker-specific parsers rejected
   both documents.
3. The successful IR and wire paths for HUM, IART, and GRMN were 145–310
   seconds behind their published timestamps. The listing/feed polling path
   needs per-request timing and candidate-discovery instrumentation.
4. SEC discovery was consistently about 47–78 seconds behind normalized
   acceptance time. The database does not show whether this delay belongs to
   SEC-API WebSocket, SEC polling, exhibit discovery, or document fetch.
5. IART's second company-IR candidate spent 42.479 seconds between event
   receipt and fact persistence. Runtime logs for the replaced container are
   no longer available, so the current database cannot split that interval
   into queueing, document fetch, and parsing.
6. A single `source_latency_ms` field is insufficient. We need at least:
   listing observed, document fetch started/completed, parse started/completed,
   fact persisted, claim started, and exchange response received.

## Next work

The next step should make future measurements trustworthy before tuning
polling intervals:

1. persist the concrete transport (`sec_api_websocket`,
   `sec_current_poll`, `company_ir_poll`, or wire provider);
2. persist monotonic stage timings for discovery, fetch, parse, fact
   persistence, decision, and exchange;
3. make the run journal select the winning fact only and use normalized SEC
   acceptance timestamps;
4. add tests for duplicate facts arriving after a claim so they cannot create
   negative decision latency.

After instrumentation is complete, replay and fix CBRE, WING, PAG, and ARCC
against their exact production documents.
