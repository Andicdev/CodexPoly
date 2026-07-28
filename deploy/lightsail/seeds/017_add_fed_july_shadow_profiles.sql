-- Add the five July 2026 FOMC decision markets.
-- Profiles remain DISABLED and schedules remain AUTO_PREFLIGHT. This seed
-- cannot authorize live trading.

BEGIN;

CREATE TEMP TABLE fed_july_batch (
    profile_key text PRIMARY KEY,
    rule_key text NOT NULL UNIQUE,
    scope_id text NOT NULL UNIQUE,
    rate_bucket text NOT NULL UNIQUE,
    market_slug text NOT NULL UNIQUE,
    condition_id text NOT NULL UNIQUE
) ON COMMIT DROP;

INSERT INTO fed_july_batch VALUES
(
    'fed-jul29-no-change',
    'fed-jul29-no-change',
    'fed:fomc:2026-07-29:no_change',
    'no_change',
    'will-there-be-no-change-in-fed-interest-rates-after-the-july-2026-meeting',
    '0x8bf1c1536ecb1c08fe13c6b71e8ab1f58bf3461c4cb79f5f1679f869a06aef86'
),
(
    'fed-jul29-increase-25',
    'fed-jul29-increase-25',
    'fed:fomc:2026-07-29:increase_25',
    'increase_25',
    'will-the-fed-increase-interest-rates-by-25-bps-after-the-july-2026-meeting',
    '0xb5c0abeecb5502e6e8d83155c27819174d8317af3c425c3afc5a8c45257a3793'
),
(
    'fed-jul29-increase-50-plus',
    'fed-jul29-increase-50-plus',
    'fed:fomc:2026-07-29:increase_50_plus',
    'increase_50_plus',
    'will-the-fed-increase-interest-rates-by-50-bps-after-the-july-2026-meeting',
    '0x2a28cc33492516116690a20d290f9922acbe0ed367ff52a6082154474c7f2971'
),
(
    'fed-jul29-decrease-25',
    'fed-jul29-decrease-25',
    'fed:fomc:2026-07-29:decrease_25',
    'decrease_25',
    'will-the-fed-decrease-interest-rates-by-25-bps-after-the-july-2026-meeting',
    '0x4ede078cae84a5877ac32d7fb48811e5c23549a1904b7df06ff7935c6d79d831'
),
(
    'fed-jul29-decrease-50-plus',
    'fed-jul29-decrease-50-plus',
    'fed:fomc:2026-07-29:decrease_50_plus',
    'decrease_50_plus',
    'will-the-fed-decrease-interest-rates-by-50-bps-after-the-july-2026-meeting',
    '0x3d675f1c88099a57c12abca632cf926be1bf430125168321de06234e9930fe1a'
);

DO $guard$
BEGIN
    IF (
        SELECT count(*)
        FROM trading_account_metadata
        WHERE account_name = 'abccbaq'
          AND wallet_address =
              '0x343FDd2bf9272Bd12cffBFE510f3969F57E36Df2'
          AND is_active = TRUE
    ) <> 1 THEN
        RAISE EXCEPTION 'reviewed trading account guard failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE source_name = 'fed_fomc'
          AND status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'an enabled FED execution profile already exists';
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
SELECT
    batch.profile_key,
    batch.scope_id,
    'fed_fomc',
    (
        'https://polymarket.com/event/fed-decision-in-july-181/'
        || batch.market_slug
    ),
    'abccbaq',
    batch.condition_id,
    0.999,
    0.999,
    50,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-29 17:55:00+00',
    TIMESTAMPTZ '2026-07-29 18:20:00+00',
    jsonb_build_object(
        'profile_template_key', 'default',
        'decision_id', 'fed:fomc:2026-07-29',
        'rule_key', batch.rule_key,
        'rate_bucket', batch.rate_bucket
    ),
    'DISABLED'
FROM fed_july_batch AS batch
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

INSERT INTO resolution_profile_schedules (
    schedule_key,
    profile_key,
    automation_mode,
    preflight_at,
    activate_at,
    deactivate_at,
    metadata,
    state
)
SELECT
    'schedule:' || batch.profile_key,
    batch.profile_key,
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-29 17:30:00+00',
    TIMESTAMPTZ '2026-07-29 17:55:00+00',
    TIMESTAMPTZ '2026-07-29 18:20:00+00',
    jsonb_build_object(
        'seed', '017_add_fed_july_shadow_profiles',
        'decision_id', 'fed:fomc:2026-07-29',
        'preflight_lead_minutes', 25
    ),
    'PENDING'
FROM fed_july_batch AS batch
ON CONFLICT (schedule_key) DO UPDATE
SET
    automation_mode = EXCLUDED.automation_mode,
    preflight_at = EXCLUDED.preflight_at,
    activate_at = EXCLUDED.activate_at,
    deactivate_at = EXCLUDED.deactivate_at,
    metadata = EXCLUDED.metadata,
    updated_at = now()
WHERE resolution_profile_schedules.state = 'PENDING';

DO $verification$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN fed_july_batch AS batch
          ON batch.profile_key = profile.profile_key
        WHERE profile.scope_id = batch.scope_id
          AND profile.source_name = 'fed_fomc'
          AND profile.source_reference = (
              'https://polymarket.com/event/fed-decision-in-july-181/'
              || batch.market_slug
          )
          AND profile.account_name = 'abccbaq'
          AND profile.condition_id = batch.condition_id
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 50
          AND profile.lifecycle_kind = 'reprice_on_tick_change'
          AND profile.old_tick = 0.01
          AND profile.new_tick = 0.001
          AND profile.max_reprices = 1
          AND profile.prepare_from =
              TIMESTAMPTZ '2026-07-29 17:55:00+00'
          AND profile.expires_at =
              TIMESTAMPTZ '2026-07-29 18:20:00+00'
          AND profile.metadata ->> 'rate_bucket' =
              batch.rate_bucket
          AND profile.status = 'DISABLED'
    ) <> 5 THEN
        RAISE EXCEPTION 'FED July execution profile batch mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN fed_july_batch AS batch
          ON batch.profile_key = schedule.profile_key
        WHERE schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-29 17:30:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-29 17:55:00+00'
          AND schedule.deactivate_at =
              TIMESTAMPTZ '2026-07-29 18:20:00+00'
          AND schedule.state = 'PENDING'
    ) <> 5 THEN
        RAISE EXCEPTION 'FED July AUTO_PREFLIGHT schedule batch mismatch';
    END IF;

    SELECT SUM(
        profile.quantity * GREATEST(
            profile.yes_desired_price,
            profile.no_desired_price
        )
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles AS profile
    JOIN fed_july_batch AS batch
      ON batch.profile_key = profile.profile_key;

    IF reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'FED July reviewed notional exceeds 1000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims AS claim
        JOIN fed_july_batch AS batch
          ON batch.scope_id = claim.scope_id
    ) THEN
        RAISE EXCEPTION 'FED July execution claim must not exist';
    END IF;
END
$verification$;

COMMIT;
