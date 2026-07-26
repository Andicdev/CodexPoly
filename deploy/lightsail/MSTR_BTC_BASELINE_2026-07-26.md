# MSTR BTC baseline deployment checkpoint

Date: 2026-07-26

## Reviewed code

- Parser commit: `18b0117`
- Holdings-state commit: `007451a`
- Guarded management commit: `de50bd4`
- Migration:
  `cbr_trading/migrations/008_add_mstr_btc_holdings_state.sql`

The management commit passed the repository secret scan and 466 unit tests.

## Applied database state

Migration 008 was applied through the fixed stdin-only runners, first to
staging and then to production. It created only:

- `mstr_btc_holdings_state`;
- its provider-event uniqueness index;
- its validated baseline-selection index;
- the trigger function and trigger that reject updates and deletes.

No legacy table or column was altered or removed.

## Seeded public baseline

Both environments contain the reviewed July 20 SEC state:

- holdings: `843775` BTC;
- reported as of: July 19, 2026 with date-only precision;
- SEC acceptance: July 20, 2026 at 12:00:16 UTC;
- accession: `0001193125-26-308369`;
- validation status: `VALIDATED`.

The staging seed was run twice successfully to prove idempotency.

## Read-only invariant

`deploy/lightsail/mstr_btc/002_verify_jul21_27_baseline.sql` passed in both
environments. It confirmed:

- the append-only trigger exists;
- exactly one matching July 20 SEC baseline exists;
- both `as_of` and `observed_at` precede July 21 at 04:00 UTC;
- the pinned row contains `843775` BTC;
- no MSTR execution profile or execution claim exists.

No worker, trading overlay, execution profile, or live-trading guard was
changed during this deployment.

After the database operations, a read-only Docker status check confirmed that
the production `earnings-worker`, base `resolution-worker`, and PostgreSQL
containers all remained `running`. Neither worker was recreated as part of
this checkpoint.
