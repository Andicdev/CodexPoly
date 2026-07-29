# July 29 official-IR parser replay

## Scope

This checkpoint reproduces the July 29 production parser outcomes for CBRE,
WING, and IART against the exact public company-IR releases. It changes parser
code and tests only. No production profile, schedule, worker, database row, or
order was changed.

The production source inventory can be inspected with the read-only query
`checks/diagnose_july_29_ir_parser_sources.sql`. Exact source-shaped regression
fixtures are in `tests/test_earnings_july_29_sec_parsers.py`.

## Exact releases

| Ticker | Official release | Market metric |
| --- | --- | --- |
| CBRE | `https://ir.cbre.com/press-releases/detail/268/cbre-group-inc-reports-financial-results-for-q2-2026` | GAAP diluted EPS |
| WING | `https://ir.wingstop.com/wingstop-inc-reports-fiscal-second-quarter-financial-results-4/` | GAAP diluted EPS |
| IART | `https://investor.integralife.com/news-releases/news-release-details/integra-lifesciences-reports-second-quarter-2026-financial` | adjusted diluted EPS |

## Reproduced causes

### CBRE

The production parser expected the historical wording `GAAP EPS up/down ...
to`. The Q2 2026 release instead used `Key Highlights: GAAP EPS of $0.69 and
Core EPS of $1.56`, so the parser returned `cbre_gaap_eps_not_found`.

Parser version 2 accepts the new exact GAAP label while preserving the old
label and still rejects guidance-only text. The replay resolves to `0.69`.

### WING

The production parser expected `Net income of ... million, or ... per diluted
share`. The Q2 2026 release instead used `Net income, increased 16.9% to $31.3
million, or $1.15 per diluted share`, so the parser returned
`wingstop_gaap_eps_not_found`.

Parser version 2 accepts the new net-income sentence while preserving the old
label and does not select the later adjusted-EPS value. The replay resolves to
`1.15`.

### IART

The existing parser correctly selects `Adjusted earnings per diluted share of
$0.56` and does not select GAAP EPS of `$0.06`. It remains parser version 1.
There was no parser defect to fix.

The exact IART page exposed a separate transport diagnostic: in the local
verification environment, the standard-library `urllib` request did not
receive a response from the canonical slug within either 20 or 50 seconds.
A bounded `requests` read of that slug returned in under one second once, then
timed out in subsequent 15- and 20-second checks. The equivalent official
Drupal node URL, `https://investor.integralife.com/node/27956`, returned the
same full release in under one second during an isolated check. A network-bound
replay was intentionally not added to the automated test suite because the
source itself is not deterministic.

This route-dependent behavior is consistent with the production observation
that the second IART company-IR candidate took 42.479 seconds from source-event
receipt to fact persistence, but it does not prove that all of that interval
was HTTP fetch time. The production fetch, queue, and parse stages must be
measured separately before changing the live transport.

## Safety properties retained

- parser identity, ticker, CIK, period, metric, basis, and source authority are
  still checked fail-closed;
- guidance-only CBRE text remains `NO_MATCH`;
- WING resolves GAAP diluted EPS, not the adjusted value appearing later in the
  same sentence block;
- all three values were checked against the full public HTML documents and
  retained as exact source-shaped regression fragments;
- no network replay content is stored in the repository.

## Follow-up

The parser defects for CBRE and WING are fixed locally. The IART result should
feed the source-transport work: compare `urllib` and `requests` from the
production network with stage telemetry before selecting or deploying a new
HTTP client.
