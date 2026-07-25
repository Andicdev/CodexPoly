-- Read-only verification immediately after guarded activation and before
-- starting the production live resolution worker.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() <
        TIMESTAMPTZ '2026-07-27 19:00:00+00'
       OR now() >=
        TIMESTAMPTZ '2026-07-28 03:00:00+00'
    THEN
        RAISE EXCEPTION 'outside the NVTS execution window';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'expected exactly one enabled profile';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-nvts-2026q2'
          AND scope_id = 'earnings:NVTS:2026Q2'
          AND source_name = 'earnings_resolution'
          AND account_name = 'abccbaq'
          AND condition_id =
              '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 50
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND prepare_from =
              TIMESTAMPTZ '2026-07-27 19:00:00+00'
          AND expires_at =
              TIMESTAMPTZ '2026-07-28 03:00:00+00'
          AND status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'NVTS profile is not safely enabled';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM trading_account_metadata
        WHERE account_name = 'abccbaq'
          AND wallet_address =
              '0x343FDd2bf9272Bd12cffBFE510f3969F57E36Df2'
          AND venue = 'polymarket_clob'
          AND signature_type = 2
          AND is_active = true
    ) THEN
        RAISE EXCEPTION 'NVTS trading account metadata is not active';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:NVTS:2026Q2'
          AND status = 'VALIDATED'
    ) THEN
        RAISE EXCEPTION 'an NVTS fact appeared before live startup';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:NVTS:2026Q2'
    ) THEN
        RAISE EXCEPTION 'an NVTS execution claim already exists';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'an active NVTS order group already exists';
    END IF;
END
$verify$;

ROLLBACK;
