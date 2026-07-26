# MSTR BTC append-only audit and signals checkpoint

Date: 2026-07-26

## Reviewed release

- Source commit: `e26feb9`
- Source archive SHA256:
  `c465698fd5b87bb9df5f55293ccd0d954cb49d10dbd18ca7d60b8f8e2cce6ff1`
- Image:
  `codexpoly@sha256:25c7fbabb910c1a0cdcacb2b8472a822fd433f9f52b438855f79f0cfabd6eaa9`
- Image archive SHA256:
  `a13b822b4d5cd43cdd909ea66b714dcff9e5daaf4f89f1f458c6a2db2814ae8d`

The local working-tree suite passed 489 tests with one skip. The image was
built from a clean `git archive`; its Docker build independently passed the
repository secret scan and all 474 tests contained in the reviewed commit.

## Migration

Migration 009 was applied first to staging and then to production through the
fixed stdin-only migration runners. It created only:

- `mstr_btc_source_events`;
- `mstr_btc_fact_candidates`;
- `mstr_btc_processing_results`.

Each table has a database trigger that rejects updates and deletes. Source
events and facts are independently idempotent. `ERROR` processing results are
retryable, while a partial unique index permits only one terminal
`ACCEPTED`, `NO_MATCH`, or `QUARANTINED` result per source event.

The checked-in read-only invariant passed in both environments. It confirmed
the three append-only triggers, referential integrity, the pre-window
`843775` BTC baseline, and the absence of MSTR execution profiles and claims.

## Resolution signals

One validated weekly fact now fans out into three independent source-neutral
signals:

- `mstr-btc:2026-07-21:2026-07-27:purchase-any`;
- `mstr-btc:2026-07-21:2026-07-27:purchase-over-1000`;
- `mstr-btc:2026-07-21:2026-07-27:sale-any`.

The signal values are BTC quantities. Comparison remains a later strategy
responsibility. A holdings-derived acquisition within one BTC of the strict
1000-BTC boundary is quarantined unless the document provides an explicit
quantity. A missing opposite operation may resolve to zero only when the
holdings equation cross-checks within the parser tolerance.

No MSTR signal is connected to a strategy, execution profile,
`OrderIntent`, or executor in this release.

## Promotion evidence

The immutable image was promoted through staging before production. Both
source workers reported:

- `connected=True`;
- `watches=4`;
- `processed=0`;
- `signals=0`;
- `mstr_accepted=0`;
- `errors=0`.

Only `earnings-worker` was recreated. The production `resolution-worker`
remained on
`sha256:2c408499ddd01367fe097586346bd6cbe5073f5c82b8831d4d642c839cf31c30`.
No trading-overlay container was running.
