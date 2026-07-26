# MSTR BTC resolution flow

The MSTR source reuses the shared SEC WebSocket transport. An accepted
holdings-first fact is persisted in the append-only MSTR audit tables and
fans out into three independent market scopes:

- any BTC purchase;
- a strict purchase greater than 1000 BTC;
- any BTC sale.

The source owns fact interpretation only. It does not import a trading
account, build an `OrderIntent`, or call an executor. The separate hosted
composition binds each signal scope to its own execution profile and numeric
strategy without adding trading dependencies to the source service.

## Hosted composition

`MstrBtcHostedResolutionWorker` is part of the separate
`resolution-worker` service. It:

1. loads only enabled profiles whose source is `mstr_btc_resolution`;
2. verifies their `condition_id` and Polymarket URL against the checked-in
   market bindings;
3. reads only `VALIDATED` facts for the required weekly scope;
4. creates one source, numeric strategy, and prepared executor per market;
5. expires a prepared profile without consuming a late fact when its window
   closes.

The production profiles are seeded separately and remain `DISABLED`. Their
defaults are desired price `0.999` on both outcomes, quantity `50`, and one
tick reprice from `0.01` to `0.001`.

## Production authenticated preflight

The production preflight is deliberately sequential. Exactly one of the
three checked-in profiles is enabled, authenticated, and restored to
`DISABLED` before the next profile is touched. The SQL files are in:

```text
deploy/lightsail/mstr_btc/preflight
```

For each profile:

1. apply its guarded `00N_enable_*.sql`;
2. run the immutable image with:

   ```text
   python -u -m cbr_trading.simulations.production_mstr_btc_preflight \
     --confirm PRODUCTION_MSTR_AUTHENTICATED_PREFLIGHT \
     --profile-key PROFILE_KEY
   ```

3. apply `004_restore_all_disabled.sql` even when the runner fails;
4. apply `005_verify_disabled_resolution_profiles.sql`.

The runner requires production internal PostgreSQL, preflight mode, disabled
supervision and live trading, the `abccbaq` metadata-plus-secret account
source, and exact limits `50 / 50 / 100`. It loads both outcome books,
calculates the tick-aligned price, checks current minimum size and collateral,
and pre-signs both GTC alternatives. It never polls the MSTR source, calls
executor `execute`, or submits an order. Its JSON output excludes token IDs,
signatures, wallet details, balances, and secret values.

The hosted layer also enforces the aggregate limit across every enabled
profile, including profiles owned by other source workers. At the configured
desired price, three quantity-50 profiles have a conservative worst-case
selected-outcome notional of `149.85`, so they cannot be enabled together
under the reviewed cap of `100`. A later live transition therefore requires
an explicit risk decision: reduce the profile set or quantity, or approve a
larger aggregate cap.

## Non-submitting end-to-end simulation

Run:

```text
python -m cbr_trading.simulations.mstr_btc_resolution
```

The simulation bypasses document parsing and does not use a database,
network, account key, or persisted execution profile. Three deterministic
facts cover:

- a 1500 BTC purchase: `YES / YES / NO`;
- an exact 1000 BTC purchase: `YES / NO / NO`;
- a 32 BTC sale: `NO / NO / YES`.

For every scenario, three independent coordinators exercise:

```text
MstrBtcResolutionSource
    -> ResolutionSignal
    -> NumericThresholdStrategy
    -> OrderIntent
    -> DryRunPreparedExecutor
```

Every market prepares both alternatives at desired price `0.999`, quantity
`50`, with the single `0.01 -> 0.001` tick-reprice policy. Synthetic signal
IDs are deliberately outside production scopes, execution is always
`DRY_RUN`, and no production idempotency claim is created.

The staging persisted-fact smoke uses a real append-only audit row but a
unique `staging-mstr-smoke-*` weekly scope:

```text
python -m cbr_trading.simulations.staging_mstr_btc_shadow \
  --confirm STAGING_MSTR_SHADOW
```

It temporarily enables three synthetic profiles, runs the hosted worker
through `DryRunPreparedExecutor`, and disables the profiles in `finally`.
The synthetic audit row remains immutable by design and cannot collide with
a production rule or execution claim.
