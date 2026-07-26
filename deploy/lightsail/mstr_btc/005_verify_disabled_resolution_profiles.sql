-- Read-only invariant for checked-in MSTR market identities and profiles.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                (
                    'mstr-jul21-27-purchase-any',
                    'mstr-btc:2026-07-21:2026-07-27:purchase-any',
                    'https://polymarket.com/event/will-microstrategy-announce-a-bitcoin-purchase-july-21-27',
                    '0xa17d770b4962398a55d4b1d87e083ba986ab8fff4e8ca0c794fc3a4d1f18051a'
                ),
                (
                    'mstr-jul21-27-purchase-over-1000',
                    'mstr-btc:2026-07-21:2026-07-27:purchase-over-1000',
                    'https://polymarket.com/event/microstrategy-announces-1000-btc-purchase-july-21-27',
                    '0x53e75dd47cd2e9076955ca4e8e8827c5718dd1e9566d49d74a831b0465501ec1'
                ),
                (
                    'mstr-jul21-27-sale-any',
                    'mstr-btc:2026-07-21:2026-07-27:sale-any',
                    'https://polymarket.com/event/will-microstrategy-announce-selling-any-bitcoin-july-21-27',
                    '0xc937afbe3ce062c934d2922c313a8990907f1d382a55e8ee56d36a5b0359500b'
                )
        ) AS expected(
            profile_key,
            scope_id,
            source_reference,
            condition_id
        )
        LEFT JOIN resolution_execution_profiles AS actual
          ON actual.profile_key = expected.profile_key
        WHERE actual.id IS NULL
           OR actual.scope_id IS DISTINCT FROM expected.scope_id
           OR actual.source_name IS DISTINCT FROM
              'mstr_btc_resolution'
           OR actual.source_reference IS DISTINCT FROM
              expected.source_reference
           OR actual.account_name IS DISTINCT FROM 'abccbaq'
           OR actual.condition_id IS DISTINCT FROM
              expected.condition_id
           OR actual.yes_desired_price IS DISTINCT FROM 0.999
           OR actual.no_desired_price IS DISTINCT FROM 0.999
           OR actual.quantity IS DISTINCT FROM 50
           OR actual.lifecycle_kind IS DISTINCT FROM
              'reprice_on_tick_change'
           OR actual.old_tick IS DISTINCT FROM 0.01
           OR actual.new_tick IS DISTINCT FROM 0.001
           OR actual.max_reprices IS DISTINCT FROM 1
           OR actual.prepare_from IS DISTINCT FROM
              TIMESTAMPTZ '2026-07-27 06:00:00+00'
           OR actual.expires_at IS DISTINCT FROM
              TIMESTAMPTZ '2026-07-28 04:00:00+00'
           OR actual.status IS DISTINCT FROM 'DISABLED'
    ) THEN
        RAISE EXCEPTION 'checked-in MSTR profiles do not match';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE source_name = 'mstr_btc_resolution'
          AND status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'an MSTR execution profile is enabled';
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
        RAISE EXCEPTION 'MSTR execution claims already exist';
    END IF;
END
$verify$;

ROLLBACK;
