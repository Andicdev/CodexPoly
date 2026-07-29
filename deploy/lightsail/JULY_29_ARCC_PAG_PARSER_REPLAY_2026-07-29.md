# July 29 ARCC and PAG parser replay

## Scope

This checkpoint closes the two parser gaps left after the July 29 pre-market
latency review and the earlier CBRE/WING replay:

- ARCC non-GAAP Core EPS;
- PAG GAAP earnings per share.

Production was inspected through a read-only database transaction and
sanitized allowlisted output. No profile, schedule, source event, fact,
execution claim, order, or run-journal row was changed.

The refreshed production audit reproduced the earlier checkpoint without a
classification change:

- five submitted orders were latency misses with no observed fill;
- CBRE and WING were parser misses already fixed in parser version 2;
- ARCC and PAG remained the two unresolved parser conflicts.

## Exact production documents

ARCC:

`https://www.sec.gov/Archives/edgar/data/1287750/000162828026050303/arccq2-2026exhibit991.htm`

The current and comparison columns appear in the same operating-results row:

- current header: `Q2-26`;
- comparison header: `Q2-25`;
- current Core EPS: `0.47`;
- comparison Core EPS: `0.50`.

The generic labelled parser correctly refused to guess between the two
distinct values, producing `conflicting_ares_capital_core_eps_values`.

PAG:

`https://www.prnewswire.com/news-releases/penske-automotive-group-reports-quarterly-results-302837495.html`

The release contains GAAP, adjusted, prior-year, quarterly, and six-month EPS
values. The reported current-quarter GAAP EPS is `3.96`; the headline also
contains adjusted EPS `3.62`, while later comparison and reconciliation
tables contain additional EPS values. The generic labelled parser therefore
produced `conflicting_penske_automotive_gaap_eps_values`.

## Parser changes

`AresCapitalCoreEpsParser` version 2 now:

- requires the exact current/prior quarter table header;
- locates the Core EPS row after that header;
- selects only the first, current-period value;
- retains the generic single-value fallback for older official release
  shapes;
- rejects guidance, outlook, and expected-value text.

`PenskeAutomotiveGaapEpsParser` version 2 now:

- prefers the reported GAAP EPS in the exact current-quarter results
  sentence;
- does not select adjusted EPS, prior-year comparison values, six-month
  values, or reconciliation-table values;
- rejects expected and guidance-prefixed EPS.

Both parsers retain the existing scope, ticker, CIK, fiscal period, metric,
basis, official-authority, and value-range guards.

## Verification

Short source-shaped regression fixtures reproduce the multi-value layouts.
The complete public production documents were also fetched once and passed
through the updated parsers without storing their contents:

- ARCC: `accepted`, reason `official_ares_capital_core_eps`, value `0.47`,
  parser version `2`;
- PAG: `accepted`, reason
  `official_penske_automotive_gaap_diluted_eps`, value `3.96`, parser
  version `2`.

The July 29 diagnostic now includes the public source and filing links in its
sanitized failure records. It also supports `--skip-remote`, allowing a
strictly database-only audit without calling the exchange order API.

## Promotion boundary

This checkpoint does not deploy or replay either document into production.
Both July 29 profiles are already disabled and their schedules are terminal.
Historical failed source events remain unchanged.

Promotion should use a new clean immutable image and the normal staging-first
workflow. A production worker restart should happen only after confirming
that it does not interrupt an active market block.
