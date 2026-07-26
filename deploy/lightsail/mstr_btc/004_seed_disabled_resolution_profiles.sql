-- Guarded non-secret MSTR execution configuration.
-- All profiles remain DISABLED. This file does not create execution claims.

BEGIN;

LOCK TABLE resolution_execution_profiles
    IN SHARE ROW EXCLUSIVE MODE;

DO $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM resolution_profile_templates
        WHERE template_key = 'default'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 50
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
    ) THEN
        RAISE EXCEPTION 'default resolution profile template mismatch';
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
        RAISE EXCEPTION 'MSTR trading account metadata mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE source_name = 'mstr_btc_resolution'
          AND status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'an MSTR execution profile is already enabled';
    END IF;
END
$guard$;

INSERT INTO resolution_execution_profiles (
    profile_key,
    scope_id,
    source_name,
    source_reference,
    account_name,
    condition_id,
    yes_desired_price,
    no_desired_price,
    quantity,
    lifecycle_kind,
    old_tick,
    new_tick,
    max_reprices,
    prepare_from,
    expires_at,
    metadata,
    status
)
VALUES
    (
        'mstr-jul21-27-purchase-any',
        'mstr-btc:2026-07-21:2026-07-27:purchase-any',
        'mstr_btc_resolution',
        'https://polymarket.com/event/will-microstrategy-announce-a-bitcoin-purchase-july-21-27',
        'abccbaq',
        '0xa17d770b4962398a55d4b1d87e083ba986ab8fff4e8ca0c794fc3a4d1f18051a',
        0.999,
        0.999,
        50,
        'reprice_on_tick_change',
        0.01,
        0.001,
        1,
        TIMESTAMPTZ '2026-07-27 06:00:00+00',
        TIMESTAMPTZ '2026-07-28 04:00:00+00',
        '{
            "market_slug": "will-microstrategy-announce-a-bitcoin-purchase-july-21-27",
            "profile_template_key": "default",
            "rule_key": "mstr-btc-jul21-27-purchase-any",
            "ticker": "MSTR",
            "weekly_scope_id": "mstr-btc:2026-07-21:2026-07-27"
        }'::jsonb,
        'DISABLED'
    ),
    (
        'mstr-jul21-27-purchase-over-1000',
        'mstr-btc:2026-07-21:2026-07-27:purchase-over-1000',
        'mstr_btc_resolution',
        'https://polymarket.com/event/microstrategy-announces-1000-btc-purchase-july-21-27',
        'abccbaq',
        '0x53e75dd47cd2e9076955ca4e8e8827c5718dd1e9566d49d74a831b0465501ec1',
        0.999,
        0.999,
        50,
        'reprice_on_tick_change',
        0.01,
        0.001,
        1,
        TIMESTAMPTZ '2026-07-27 06:00:00+00',
        TIMESTAMPTZ '2026-07-28 04:00:00+00',
        '{
            "market_slug": "microstrategy-announces-1000-btc-purchase-july-21-27",
            "profile_template_key": "default",
            "rule_key": "mstr-btc-jul21-27-purchase-over-1000",
            "ticker": "MSTR",
            "weekly_scope_id": "mstr-btc:2026-07-21:2026-07-27"
        }'::jsonb,
        'DISABLED'
    ),
    (
        'mstr-jul21-27-sale-any',
        'mstr-btc:2026-07-21:2026-07-27:sale-any',
        'mstr_btc_resolution',
        'https://polymarket.com/event/will-microstrategy-announce-selling-any-bitcoin-july-21-27',
        'abccbaq',
        '0xc937afbe3ce062c934d2922c313a8990907f1d382a55e8ee56d36a5b0359500b',
        0.999,
        0.999,
        50,
        'reprice_on_tick_change',
        0.01,
        0.001,
        1,
        TIMESTAMPTZ '2026-07-27 06:00:00+00',
        TIMESTAMPTZ '2026-07-28 04:00:00+00',
        '{
            "market_slug": "will-microstrategy-announce-selling-any-bitcoin-july-21-27",
            "profile_template_key": "default",
            "rule_key": "mstr-btc-jul21-27-sale-any",
            "ticker": "MSTR",
            "weekly_scope_id": "mstr-btc:2026-07-21:2026-07-27"
        }'::jsonb,
        'DISABLED'
    )
ON CONFLICT (profile_key) DO UPDATE
SET
    scope_id = EXCLUDED.scope_id,
    source_name = EXCLUDED.source_name,
    source_reference = EXCLUDED.source_reference,
    account_name = EXCLUDED.account_name,
    condition_id = EXCLUDED.condition_id,
    yes_desired_price = EXCLUDED.yes_desired_price,
    no_desired_price = EXCLUDED.no_desired_price,
    quantity = EXCLUDED.quantity,
    lifecycle_kind = EXCLUDED.lifecycle_kind,
    old_tick = EXCLUDED.old_tick,
    new_tick = EXCLUDED.new_tick,
    max_reprices = EXCLUDED.max_reprices,
    prepare_from = EXCLUDED.prepare_from,
    expires_at = EXCLUDED.expires_at,
    metadata = EXCLUDED.metadata,
    updated_at = now()
WHERE resolution_execution_profiles.status = 'DISABLED';

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'mstr-jul21-27-purchase-any',
            'mstr-jul21-27-purchase-over-1000',
            'mstr-jul21-27-sale-any'
        )
          AND source_name = 'mstr_btc_resolution'
          AND account_name = 'abccbaq'
          AND status = 'DISABLED'
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
        RAISE EXCEPTION 'disabled MSTR profiles do not match';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE source_name = 'mstr_btc_resolution'
          AND status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'MSTR execution profile became enabled';
    END IF;
END
$verify$;

COMMIT;
