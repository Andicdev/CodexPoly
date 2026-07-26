-- Guarded production activation for all three MSTR July 21-27 profiles.
-- This changes only their status and never changes trading parameters.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';

LOCK TABLE resolution_execution_profiles
    IN SHARE ROW EXCLUSIVE MODE;

DO $enable$
DECLARE
    activation_time timestamptz := clock_timestamp();
    changed_rows integer;
BEGIN
    IF activation_time <
        TIMESTAMPTZ '2026-07-27 06:00:00+00'
       OR activation_time >=
        TIMESTAMPTZ '2026-07-28 04:00:00+00'
    THEN
        RAISE EXCEPTION 'outside the guarded MSTR activation window';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'another execution profile is already enabled';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE source_name = 'mstr_btc_resolution'
          AND status = 'DISABLED'
    ) <> 3 THEN
        RAISE EXCEPTION 'expected three disabled MSTR profiles';
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

    WITH expected(
        profile_key,
        scope_id,
        source_reference,
        condition_id,
        rule_key,
        market_slug
    ) AS (
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
    )
    UPDATE resolution_execution_profiles AS actual
    SET
        status = 'ENABLED',
        updated_at = now()
    FROM expected
    WHERE actual.profile_key = expected.profile_key
      AND actual.scope_id = expected.scope_id
      AND actual.source_name = 'mstr_btc_resolution'
      AND actual.source_reference = expected.source_reference
      AND actual.account_name = 'abccbaq'
      AND actual.condition_id = expected.condition_id
      AND actual.yes_desired_price = 0.999
      AND actual.no_desired_price = 0.999
      AND actual.quantity = 50
      AND actual.lifecycle_kind = 'reprice_on_tick_change'
      AND actual.old_tick = 0.01
      AND actual.new_tick = 0.001
      AND actual.max_reprices = 1
      AND actual.prepare_from =
          TIMESTAMPTZ '2026-07-27 06:00:00+00'
      AND actual.expires_at =
          TIMESTAMPTZ '2026-07-28 04:00:00+00'
      AND actual.metadata @> jsonb_build_object(
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
      AND actual.status = 'DISABLED';

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 3 THEN
        RAISE EXCEPTION 'MSTR live profiles did not match the safe baseline';
    END IF;
END
$enable$;

COMMIT;
