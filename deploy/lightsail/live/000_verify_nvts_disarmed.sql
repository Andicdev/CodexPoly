-- Read-only readiness check before the NVTS live activation sequence.
-- It proves the production database is fail-closed and has no stale signal
-- or execution state that could be replayed when the live worker starts.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE status <> 'DISABLED'
    ) THEN
        RAISE EXCEPTION 'an execution profile is not disabled';
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
          AND status = 'DISABLED'
    ) THEN
        RAISE EXCEPTION 'NVTS profile does not match the safe baseline';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'nvts-2026q2-nongaap-eps-neg0pt04'
          AND scope_id = 'earnings:NVTS:2026Q2'
          AND ticker = 'NVTS'
          AND metric_kind = 'non_gaap_eps'
          AND comparison_op = '>'
          AND strike = -0.04
          AND rounding_places = 2
          AND condition_id =
              '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d'
          AND status IN ('SHADOW', 'WATCHING')
    ) THEN
        RAISE EXCEPTION 'NVTS source rule does not match the safe baseline';
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
        RAISE EXCEPTION 'a validated NVTS fact already exists';
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
