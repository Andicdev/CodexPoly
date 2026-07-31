# Neg-risk staging services

The staging stack runs two read-only public-data services:

```text
python -u -m neg_risk_trading.recorder_main
python -u -m neg_risk_trading.catalog_main
```

The recorder subscribes to the public Polymarket market channel for every YES and NO
asset in `fed-decision-in-september-762`, maintains local L2 books, and writes
public replay messages plus shadow route observations to the isolated
`codexpoly_neg_risk` database.

The catalog scanner exhausts the public Gamma market keyset every 15 minutes,
filters active neg-risk markets, and atomically promotes current volume,
liquidity, fee, tick, reward-term, and launch-screening metadata. A failed or
partial cursor traversal never replaces the last complete catalog.

Each service receives only the database application password. Neither has a
trading-account secret, CLOB credential, private key, Telegram credential, or
host port. Shadow mode is mandatory and the database schemas enforce
`live_orders_enabled=false`.

## Required order

1. Install the reviewed database runner updates.
2. Apply
   `neg_risk_trading/migrations/001_add_shadow_observation_tables.sql`
   through `codexpoly-staging-neg-risk-migrate`.
3. Verify the schema with
   `neg_risk_trading/checks/verify_shadow_observation_schema.sql`.
4. Apply
   `neg_risk_trading/migrations/002_add_catalog_scanner_tables.sql`
   and verify it with
   `neg_risk_trading/checks/verify_catalog_schema.sql`.
5. Apply
   `neg_risk_trading/migrations/003_add_bid_routes_and_stream_anomalies.sql`
   and verify the observation schema again.
6. Install this Compose file at
   `/opt/codexpoly/staging/apps/neg-risk/compose.yml`.
7. Set `CODEXPOLY_IMAGE_REF` to the reviewed immutable image digest and start
   the selected service explicitly.
8. Verify aggregate session/message/observation counts and the latest complete
   catalog scan. Do not return raw payload rows in ordinary deployment logs.

Production is intentionally absent from this checkpoint. Public market
recording runs in staging first; no live trading service is created.
