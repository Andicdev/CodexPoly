# July 30 post-market hardening

Status: implemented and tested locally; not deployed to production.

## Parser safety

- RIVN v4 proves prior/current year column order and quarter/YTD grouping.
- RBLX v3 proves current/prior year order and rejects unknown extra columns.
- WWD v2 proves the quarter column precedes YTD.
- EA v2 accepts only the reviewed two-column Quarterly Financial Highlights
  shape.
- Migration 021 records parse attempts by source event, parser name, and
  parser version. A new version can claim an old `NO_MATCH` once only when no
  validated/emitted fact already exists for the scope.

## Repricing lifecycle

- `submit_first=True` remains the latency-first default and documents its
  possible brief overlap.
- `submit_first=False` inspects the exact source order before replacement.
- Groups older than five seconds always inspect first and replace only the
  confirmed remainder.
- Migration 022 adds a terminal `OVERFILLED` audit. A fully terminal double
  fill becomes legacy-compatible `COMPLETED` with durable target, filled, and
  excess quantities instead of remaining a generic failed group.

## Deployment boundary

Apply migrations 021 and 022 before starting an image that contains this
change. Earnings and order-supervision readiness checks require the new
tables. A production image rollout and worker restarts require a separate
operator authorization.
