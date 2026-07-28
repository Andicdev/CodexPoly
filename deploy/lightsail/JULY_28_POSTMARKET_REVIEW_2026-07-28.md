# July 28 post-market review and corrective rollout

Date: 2026-07-28

## Outcome

The reviewed live block contained five profiles. Starbucks was deliberately
not part of this block: the issuer's official release is scheduled for the
July 29 post-market window even though the Polymarket slug references July 28.

| Ticker | Official value | Outcome | Execution | Classification |
|---|---:|---|---|---|
| CSGP | GAAP diluted EPS `0.14` | YES | not attempted | parser miss |
| CZR | adjusted diluted EPS `-0.30` | NO | accepted, open at `0.999` | latency miss |
| F | adjusted diluted EPS `0.42` | YES | not attempted | source-coverage miss |
| NXPI | non-GAAP diluted EPS `3.61` | YES | accepted, open at `0.999` | latency miss |
| V | non-GAAP diluted EPS `3.32` | YES | accepted, open at `0.999` | latency miss |

The post-release direction was correct for all five rules. No order filled.
The three submitted orders reached Polymarket correctly, but only after the
market had already moved to the terminal price. Their observed source
latencies were approximately `80.9 s`, `66.1 s`, and `57.9 s` for CZR, NXPI,
and V respectively. A release timestamp rounded to the minute can overstate
the transport component, so this number is an end-to-end source metric, not a
pure network measurement.

The accepted `0.999` orders were not cancelled or otherwise mutated during
the review or rollout.

## Root causes

1. The CoStar document contained several historical diluted-EPS values. The
   generic parser quarantined the filing instead of choosing the exact
   current-quarter headline sentence.
2. Ford published its official release as a PDF on the issuer's Q4 CDN. The
   configured SEC-only path did not see an actionable document.
3. Public feeds were requested concurrently, but processing used a
   gather-all barrier. A slow IR host could therefore delay a candidate that
   had already arrived from a faster source.
4. Public document retries could hold one polling cycle for three full
   transport timeouts.
5. Run-journal classification still required a manual SQL review after the
   block.

## Corrective changes

- CoStar parser version 2 selects the exact current-quarter headline phrase
  before considering generic table matches.
- Ford parser version 2 selects the current-year adjusted diluted EPS from
  the real PDF table layout.
- Public sources support allowlisted direct PDF documents and bounded PDF text
  extraction.
- Ford's official Q2 PDF is registered as a disabled `company_ir`
  `direct_document` source, preserving the closed live block.
- Feed results are processed as soon as each request completes. A slow feed
  no longer delays a ready candidate from another feed.
- Listing and document timeouts are separated (`2 s` and `5 s` in
  production). A failed document is retried by the next profile-gated polling
  cycle instead of blocking for three attempts.
- A background earnings run-journal reconciler records source, decision,
  execution, fill, price, and error classifications without running on the
  trading hot path. It scans only the recent window, writes only changed
  rows, and never overwrites rows marked as manually reviewed.

## Verification and deployment

- Source commit: `fb312ae`.
- Source archive SHA256:
  `4f66243056e9224d12d82b899367875fbae6033a8083d34072866db35e7e40ca`.
- Image archive SHA256:
  `eb0b8e6b1b5ca88d3143dbefab9fa420ef52b444d40ed385c6676e3b7fc6cbdd`.
- Immutable image:
  `codexpoly@sha256:cc8cf9fa5ce94ffd2f74f8e0f1ab6c9e979ebd7badf0463fa03830b24babe838`.

The local and clean Docker builds each passed the secret scan and all `720`
tests with one expected skip. Staging ran the real journal SQL against
PostgreSQL and reconciled `12` rows on its first pass without repeated
unchanged writes.

The same digest was promoted to production for `earnings-worker` and the
supervised live `resolution-worker`. The final fail-closed checks confirmed:

- both updated containers use the exact immutable digest;
- the resolution heartbeat is fresh in live, supervision, and trading mode;
- no earnings profile is enabled in the current window;
- public, SEC current-filings, and Strategy Ledger polling are inactive with
  no profile in-window;
- the SEC WebSocket is connected with zero errors;
- all five manually reviewed post-market rows remain unchanged;
- automatic journal reconciliation is persisting;
- the Ford direct-document source remains disabled with the completed block.

No order was submitted during build, staging verification, migration, or
production promotion.

## Next boundary

The July 29 profiles still require their own pre-market/post-market readiness
review, production seed, authenticated preflight, and explicit block
activation. They are not implicitly activated by this rollout.
