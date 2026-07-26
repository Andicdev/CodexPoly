-- Read-only verification immediately after guarded MSTR activation and
-- before starting the production live resolution worker.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-27 06:00:00+00'
       OR now() >= TIMESTAMPTZ '2026-07-28 04:00:00+00'
    THEN
        RAISE EXCEPTION 'outside the MSTR execution window';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
    ) <> 3 THEN
        RAISE EXCEPTION 'expected exactly three enabled profiles';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE source_name = 'mstr_btc_resolution'
          AND status = 'ENABLED'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 50
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND prepare_from =
              TIMESTAMPTZ '2026-07-27 06:00:00+00'
          AND expires_at =
              TIMESTAMPTZ '2026-07-28 04:00:00+00'
    ) <> 3 THEN
        RAISE EXCEPTION 'MSTR profiles are not safely enabled';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                (
                    'mstr-jul21-27-purchase-any',
                    'mstr-btc:2026-07-21:2026-07-27:purchase-any',
                    '0xa17d770b4962398a55d4b1d87e083ba986ab8fff4e8ca0c794fc3a4d1f18051a'
                ),
                (
                    'mstr-jul21-27-purchase-over-1000',
                    'mstr-btc:2026-07-21:2026-07-27:purchase-over-1000',
                    '0x53e75dd47cd2e9076955ca4e8e8827c5718dd1e9566d49d74a831b0465501ec1'
                ),
                (
                    'mstr-jul21-27-sale-any',
                    'mstr-btc:2026-07-21:2026-07-27:sale-any',
                    '0xc937afbe3ce062c934d2922c313a8990907f1d382a55e8ee56d36a5b0359500b'
                )
        ) AS expected(profile_key, scope_id, condition_id)
        LEFT JOIN resolution_execution_profiles AS actual
          ON actual.profile_key = expected.profile_key
        WHERE actual.id IS NULL
           OR actual.scope_id IS DISTINCT FROM expected.scope_id
           OR actual.condition_id IS DISTINCT FROM
              expected.condition_id
           OR actual.status IS DISTINCT FROM 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'an exact MSTR profile is not enabled';
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
        RAISE EXCEPTION 'MSTR trading account metadata is not active';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM mstr_btc_holdings_state
        WHERE holdings_btc = 843775
          AND as_of = TIMESTAMPTZ '2026-07-19 00:00:00+00'
          AND observed_at =
              TIMESTAMPTZ '2026-07-20 12:00:16+00'
          AND provider = 'sec'
          AND provider_event_id = '0001193125-26-308369'
          AND validation_status = 'VALIDATED'
    ) THEN
        RAISE EXCEPTION 'pinned MSTR baseline does not match';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM mstr_btc_source_events
        WHERE scope_id = 'mstr-btc:2026-07-21:2026-07-27'
    ) OR EXISTS (
        SELECT 1
        FROM mstr_btc_fact_candidates
        WHERE scope_id = 'mstr-btc:2026-07-21:2026-07-27'
    ) THEN
        RAISE EXCEPTION 'MSTR source state appeared before live startup';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'mstr-btc:2026-07-21:2026-07-27:purchase-any',
            'mstr-btc:2026-07-21:2026-07-27:purchase-over-1000',
            'mstr-btc:2026-07-21:2026-07-27:sale-any'
        )
    ) THEN
        RAISE EXCEPTION 'an MSTR execution claim already exists';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id IN (
              '0xa17d770b4962398a55d4b1d87e083ba986ab8fff4e8ca0c794fc3a4d1f18051a',
              '0x53e75dd47cd2e9076955ca4e8e8827c5718dd1e9566d49d74a831b0465501ec1',
              '0xc937afbe3ce062c934d2922c313a8990907f1d382a55e8ee56d36a5b0359500b'
          )
          AND status IN ('ACTIVE', 'REPRICING', 'FAILED')
    ) THEN
        RAISE EXCEPTION 'pending MSTR supervision state already exists';
    END IF;
END
$verify$;

ROLLBACK;
