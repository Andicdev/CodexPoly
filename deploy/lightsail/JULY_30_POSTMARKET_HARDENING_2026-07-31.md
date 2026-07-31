# July 30 post-market hardening

Status: deployed and healthy in staging and production.

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

## Immutable deployment

- Application commit: `33883ce`.
- Source archive SHA256:
  `401fa9d9201875d86b5a4928d029677a7339626cf00e7da94b1859c5033dc345`.
- Immutable image:
  `sha256:9c4654c1250f994db429d153926b4dca5fa9510ceb5cc9999de62b5c971d2e55`.
- Image archive SHA256:
  `3c63039a09b0fb5113578a977df591ffedf54e074297698ef9bd376163ff61ee`.
- OCI revision: `33883ce`.

The image was built in rootless staging from the clean Git archive. Its
Docker build repeated the secret scan and all `984` tests. Migrations 021 and
022 and the fail-closed schema verifier passed in staging before the
earnings and shadow-resolution workers were recreated. Both reported the
exact image, restart count zero, a connected SEC WebSocket, `45` aggregate
watches, no active profiles, and zero source errors.

The exact exported image archive was then checksum-verified and loaded into
the rootful production Docker runtime. Migrations 021 and 022 and the same
schema verifier passed before worker recreation. Recoverable Compose copies
were saved as:

- `compose.before-33883ce.yml`;
- `compose.trading.before-33883ce.yml`.

All five production application workers were recreated on the same immutable
image. PostgreSQL was not restarted. The existing operational settings were
preserved:

- live resolution and order supervision enabled;
- scheduler automatic live activation enabled;
- quantity, per-order notional, and aggregate caps `100 / 100 / 1000`;
- readiness non-submitting.

## Production verification

All five containers run the exact image with restart count zero. Sanitized
heartbeats confirmed:

- SEC WebSocket `connected=True`, `31` aggregate watches, and `errors=0`;
- public, SEC Current, SEC Latest, and Strategy Ledger polling inactive
  because no profile is in-window;
- live earnings, MSTR, and FED resolution with zero managed profiles;
- readiness `checked=0`, `ready=0`, `blocked=0`;
- scheduler `auto_live=True`, with zero requested, activated, blocked, or
  expired transitions;
- notification outbox with zero claimed, sent, or failed rows during rollout.

The authenticated readiness worker had no eligible profile to preflight. No
profile was enabled solely for deployment verification, so no CLOB order
request was prepared or submitted.

Read-only guards passed for the new schema, fresh fully-live resolution
heartbeat, no enabled profile, no active/imminent schedule, no pending
execution claim, and no active/repricing order group. A rollout-specific
guard also confirmed that the deployment created no new completion audit
gap.

The initial global completion verifier produced a false positive for two
deliberate non-execution terminal paths. A later read-only audit identified
HOOD (`official_result_observed_execution_missing`) and MSFT
(`official_result_parser_quarantined`). Both already had one correct
`POST_EVENT_RECONCILIATION_COMPLETED` event and no execution claim or active
order group. No historical row was rewritten. The verifier now validates
both execution completion and evidence-backed non-execution completion, and
passes in staging and production.
