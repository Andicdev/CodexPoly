# Neg-risk database migrations

These migrations belong only to the isolated `codexpoly_neg_risk` database.
They must not be applied to the core `codexpoly` database.

Migration `001` creates:

- mutable aggregate stream-session state;
- append-only public WebSocket messages for deterministic replay;
- append-only normalized route observations.

Migration `002` creates:

- scan-run audit records;
- scan-scoped staging tables so a partial Gamma traversal is never exposed as
  the current catalog;
- the atomically promoted current neg-risk event and market catalog;
- ranked-event and category-summary views.

Migration `003`:

- adds explicit `MAKER_BUY`/`MAKER_SELL` route direction;
- extends route idempotency to include direction;
- adds append-only, value-safe WebSocket anomaly diagnostics.

The schema stores no account credential, private key, authenticated order,
position, or secret. Its session constraint permits only `SHADOW` mode and
requires `live_orders_enabled=false`.

Normal recorder startup calls `ensure_ready()` and never migrates itself.
The catalog scanner follows the same rule. Apply migrations `001`, `002`, and
`003` in order through the fixed environment-specific neg-risk migration
wrapper before starting either service.
