# MSTR BTC live execution checkpoint — 2026-07-27

The first production MSTR BTC weekly-resolution window completed successfully
on the Lightsail host.

## Fixed boundary

- Account: `abccbaq`
- Immutable image:
  `codexpoly@sha256:fb2be19a7eecf1c63598c1d8caeec347741f3e45ea0fb9994548ef0eb4b3be08`
- Profiles:
  - `mstr-jul21-27-purchase-any`
  - `mstr-jul21-27-purchase-over-1000`
  - `mstr-jul21-27-sale-any`
- Quantity: `50` per selected outcome
- Desired price: `0.999`
- Effective prices: `0.999`, `0.999`, and `0.99`
- Safety caps: `50 / 50 / 1000`

## Pre-signal state

- Authenticated preflight passed for three profiles and six alternatives.
- All six orders were pre-signed.
- Collateral, SAFE wallet, market state, minimum size, and tick alignment
  passed.
- SEC WebSocket reported `connected=True`, `watches=4`, and `errors=0`.
- Strategy Ledger polling reported `active=True`, `profiles=3`, and
  `connected=True`.
- Northflank earnings, resolution, and legacy SEC duplicates were paused.
- No execution claim or order existed before the signal.

## Source result

The SEC WebSocket delivered the MSTR 8-K at `12:00:53 UTC`.

- Direct SEC exhibit fetch won in `168 ms`.
- The SEC-API archive route completed later in `4120 ms`.
- Holdings before: `843775 BTC`
- Holdings after: `843775 BTC`
- Acquired: `0 BTC`
- Sold: not confirmed
- Processing status: `ACCEPTED`
- Resolution: `NO` for all three markets

The source event, validated fact, processing result, and three resolution
signals were persisted before order submission.

## Execution result

The CLOB accepted all three submissions with HTTP `200`.

Authenticated exact-order inspection confirmed:

| Profile | Outcome | Limit | Matched | Remaining | State |
| --- | --- | ---: | ---: | ---: | --- |
| purchase-any | NO | 0.999 | 50 | 0 | FILLED |
| purchase-over-1000 | NO | 0.999 | 50 | 0 | FILLED |
| sale-any | NO | 0.99 | 50 | 0 | FILLED |

The tick-supervised `0.99` order was reconciled through the authenticated
order endpoint and its persisted group became `COMPLETED` with no error.

The execution ledger contains six terminal claims:

- three selected `NO` claims are `EXECUTED`;
- three unselected `YES` claims are `EXPIRED`.

The checked-in read-only invariant
`mstr_btc/live/003_verify_mstr_post_execution.sql` passed in production.

## Restored safe state

After all three remote orders were confirmed terminal:

- the live resolution worker was stopped;
- all resolution profiles were returned to `DISABLED`;
- the base shadow resolution worker was recreated without the trading
  overlay;
- the name-only secret check confirmed that it receives only
  `DATABASE_APP_PASSWORD`;
- Strategy Ledger polling automatically returned to inactive;
- the shared SEC WebSocket remained connected.

## Telegram follow-up

Trading was not affected by notification delivery. The outbox row was
persisted after the hot path, but Telegram delivery failed.

A read-only `getMe`/`getChat` diagnostic returned HTTP `404` for both calls,
which means the installed `TG_BOT_TOKEN` is not a valid current Bot API token.
The notification worker was stopped to prevent repeated failed calls. The
pending outbox row remains in PostgreSQL.

Recovery requires a human to reinstall a valid `TG_BOT_TOKEN` through the
existing secret installer. After a successful name-only check and diagnostic,
recreating `notification-worker` will retry the persisted notification.
