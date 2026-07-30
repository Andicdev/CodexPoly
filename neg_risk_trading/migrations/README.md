# Neg-risk database migrations

These migrations belong only to the isolated `codexpoly_neg_risk` database.
They must not be applied to the core `codexpoly` database.

Migration `001` creates:

- mutable aggregate stream-session state;
- append-only public WebSocket messages for deterministic replay;
- append-only normalized route observations.

The schema stores no account credential, private key, authenticated order,
position, or secret. Its session constraint permits only `SHADOW` mode and
requires `live_orders_enabled=false`.

Normal recorder startup calls `ensure_ready()` and never migrates itself.
Apply migration `001` explicitly through the fixed environment-specific
neg-risk migration wrapper before starting the service.
