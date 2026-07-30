# Neg-risk staging recorder

The staging service runs only:

```text
python -u -m neg_risk_trading.recorder_main
```

It subscribes to the public Polymarket market channel for every YES and NO
asset in `fed-decision-in-september-762`, maintains local L2 books, and writes
public replay messages plus shadow route observations to the isolated
`codexpoly_neg_risk` database.

The service receives only the database application password. It has no
trading-account secret, CLOB credential, private key, Telegram credential, or
host port. `NEG_RISK_RECORDER_MODE=shadow` is mandatory and the database
schema enforces `live_orders_enabled=false`.

## Required order

1. Install the reviewed database runner updates.
2. Apply
   `neg_risk_trading/migrations/001_add_shadow_observation_tables.sql`
   through `codexpoly-staging-neg-risk-migrate`.
3. Verify the schema with
   `neg_risk_trading/checks/verify_shadow_observation_schema.sql`.
4. Install this Compose file at
   `/opt/codexpoly/staging/apps/neg-risk/compose.yml`.
5. Set `CODEXPOLY_IMAGE_REF` to the reviewed immutable image digest and start
   only `neg-risk-recorder`.
6. Verify aggregate session/message/observation counts. Do not return raw
   payload rows in ordinary deployment logs.

Production is intentionally absent from this checkpoint. Public market
recording runs in staging first; no live trading service is created.
