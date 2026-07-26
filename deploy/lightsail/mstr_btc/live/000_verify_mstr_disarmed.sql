-- Read-only readiness check before the MSTR July 21-27 live activation.
-- It proves the database is fail-closed and contains no filing, fact,
-- execution, or supervision state that could be replayed on startup.

BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    pinned_id bigint;
    trigger_count integer;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE status <> 'DISABLED'
    ) THEN
        RAISE EXCEPTION 'an execution profile is not disabled';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE source_name = 'mstr_btc_resolution'
    ) <> 3 THEN
        RAISE EXCEPTION 'expected exactly three MSTR profiles';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                (
                    'mstr-jul21-27-purchase-any',
                    'mstr-btc:2026-07-21:2026-07-27:purchase-any',
                    'https://polymarket.com/event/will-microstrategy-announce-a-bitcoin-purchase-july-21-27',
                    '0xa17d770b4962398a55d4b1d87e083ba986ab8fff4e8ca0c794fc3a4d1f18051a',
                    'mstr-btc-jul21-27-purchase-any',
                    'will-microstrategy-announce-a-bitcoin-purchase-july-21-27'
                ),
                (
                    'mstr-jul21-27-purchase-over-1000',
                    'mstr-btc:2026-07-21:2026-07-27:purchase-over-1000',
                    'https://polymarket.com/event/microstrategy-announces-1000-btc-purchase-july-21-27',
                    '0x53e75dd47cd2e9076955ca4e8e8827c5718dd1e9566d49d74a831b0465501ec1',
                    'mstr-btc-jul21-27-purchase-over-1000',
                    'microstrategy-announces-1000-btc-purchase-july-21-27'
                ),
                (
                    'mstr-jul21-27-sale-any',
                    'mstr-btc:2026-07-21:2026-07-27:sale-any',
                    'https://polymarket.com/event/will-microstrategy-announce-selling-any-bitcoin-july-21-27',
                    '0xc937afbe3ce062c934d2922c313a8990907f1d382a55e8ee56d36a5b0359500b',
                    'mstr-btc-jul21-27-sale-any',
                    'will-microstrategy-announce-selling-any-bitcoin-july-21-27'
                )
        ) AS expected(
            profile_key,
            scope_id,
            source_reference,
            condition_id,
            rule_key,
            market_slug
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
           OR NOT actual.metadata @> jsonb_build_object(
               'profile_template_key',
               'default',
               'rule_key',
               expected.rule_key,
               'ticker',
               'MSTR',
               'market_slug',
               expected.market_slug,
               'weekly_scope_id',
               'mstr-btc:2026-07-21:2026-07-27'
           )
           OR actual.status IS DISTINCT FROM 'DISABLED'
    ) THEN
        RAISE EXCEPTION 'MSTR profiles do not match the safe baseline';
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

    IF to_regclass('mstr_btc_holdings_state') IS NULL
       OR to_regclass('mstr_btc_source_events') IS NULL
       OR to_regclass('mstr_btc_fact_candidates') IS NULL
       OR to_regclass('mstr_btc_processing_results') IS NULL THEN
        RAISE EXCEPTION 'MSTR source schema is not ready';
    END IF;

    SELECT count(*)
    INTO trigger_count
    FROM pg_trigger
    WHERE tgrelid IN (
        'mstr_btc_holdings_state'::regclass,
        'mstr_btc_source_events'::regclass,
        'mstr_btc_fact_candidates'::regclass,
        'mstr_btc_processing_results'::regclass
    )
      AND tgname IN (
        'trg_mstr_btc_holdings_state_append_only',
        'trg_mstr_btc_source_events_append_only',
        'trg_mstr_btc_fact_candidates_append_only',
        'trg_mstr_btc_processing_results_append_only'
    )
      AND NOT tgisinternal;

    IF trigger_count <> 4 THEN
        RAISE EXCEPTION 'MSTR append-only trigger invariant failed';
    END IF;

    SELECT id
    INTO pinned_id
    FROM mstr_btc_holdings_state
    WHERE validation_status = 'VALIDATED'
      AND as_of < TIMESTAMPTZ '2026-07-21 04:00:00+00'
      AND observed_at < TIMESTAMPTZ '2026-07-21 04:00:00+00'
    ORDER BY as_of DESC, observed_at DESC, id DESC
    LIMIT 1;

    IF pinned_id IS NULL OR NOT EXISTS (
        SELECT 1
        FROM mstr_btc_holdings_state
        WHERE id = pinned_id
          AND holdings_btc = 843775
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
    ) OR EXISTS (
        SELECT 1
        FROM mstr_btc_processing_results AS result
        JOIN mstr_btc_source_events AS event
          ON event.id = result.source_event_id
        WHERE event.scope_id = 'mstr-btc:2026-07-21:2026-07-27'
    ) THEN
        RAISE EXCEPTION 'MSTR source state already exists for the live week';
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
