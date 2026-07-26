# MSTR BTC live-readiness checkpoint

Date: 2026-07-26

## Reviewed release

- Source commit: `b8df760`
- Source archive SHA256:
  `4fce53ea0eb37e3595dcb440cfcc06240bc5d16306decd9ba90e08a4a78f7fe2`
- Image:
  `codexpoly@sha256:575bd7e96da1b4bacf5f7e890df1af8eb18855375a956ab0dd72f4f85ab6292d`
- Runtime user: `appuser`

The local working-tree secret scan passed, followed by 531 tests with one
skip. The image was built from a clean `git archive`; its Dockerfile
independently passed the secret scan and all 516 tests tracked by the reviewed
commit.

The temporary local archive and remote build directory were removed after the
archive hash matched and the image was verified.

## Restart-safe claim boundary

`PolymarketPreparedExecutor` no longer creates
`resolution_execution_claims` during warm preparation. It still:

- authenticates the account;
- loads public and authenticated books;
- validates tick, minimum size, balance, and risk caps;
- pre-signs both outcome alternatives.

After a persisted signal selects an intent, the executor atomically reserves
all alternatives for that profile immediately before the first order
submission call. A duplicate worker loses the unique-claim race before
`post_orders`. A process restart before a signal is safe because no claim
exists. A crash after reservation remains deliberately fail-closed because
the remote result may be ambiguous.

## Guarded live files

The MSTR-specific procedure is checked in under:

```text
deploy/lightsail/mstr_btc/live
```

It contains:

- a read-only disarmed invariant;
- an in-window activation that changes only the exact three profile statuses;
- a read-only live-prestart verifier;
- a runbook that reuses the common fail-closed disarm SQL.

The production disarmed invariant passed before and after image promotion. It
confirmed:

- every execution profile is disabled;
- the exact three MSTR profiles and account metadata match;
- the pinned baseline remains `843775 BTC`;
- the holdings and source audit tables have all four append-only triggers;
- no MSTR source event, fact, or processing result exists for the live week;
- no MSTR execution claim exists;
- no `ACTIVE`, `REPRICING`, or `FAILED` MSTR order group exists.

No activation SQL was applied because the guarded window begins at
2026-07-27 06:00 UTC.

## Production no-submit supervision smoke

The reviewed image was promoted only to the base production
`resolution-worker` in `shadow` mode. Its only secret mount is:

```text
/run/secrets/DATABASE_APP_PASSWORD
```

The production smoke verified:

- internal PostgreSQL supervision schema readiness;
- no pending supervision work;
- successful start, reconciliation, and stop of the real background runtime;
- six current MSTR public outcome books;
- six coarse-tick watches;
- a live public market-channel subscription;
- no trading-secret mount;
- no order inspection, cancellation, or submission call.

The sanitized result was:

```text
ok=true
runtime_started=true
runtime_reconciled=true
market_channel_connected=true
market_outcome_count=6
watch_count=6
order_inspection_called=false
order_cancellation_called=false
order_submission_called=false
trading_secrets_mounted=false
```

## Restored production state

- `resolution-worker` uses the reviewed image above.
- It remains in `shadow` mode with supervision disabled.
- All MSTR and earnings profiles remain disabled.
- The trading overlay is not running.
- `earnings-worker` remains on its prior reviewed source image.
- The SEC heartbeat reports `connected=True`, `watches=4`, and `errors=0`.
- No order was submitted.

The remaining release-time actions are the current public market check,
Northflank singleton confirmation, guarded activation after 06:00 UTC, final
authenticated preflight, explicit live approval, and live worker startup.
