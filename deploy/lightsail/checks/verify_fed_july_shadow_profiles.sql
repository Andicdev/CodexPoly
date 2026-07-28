-- Fail closed without printing profiles, schedules, accounts, or claims.

BEGIN TRANSACTION READ ONLY;

DO $verification$
DECLARE
    reviewed_notional numeric;
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

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'fed-jul29-no-change',
            'fed-jul29-increase-25',
            'fed-jul29-increase-50-plus',
            'fed-jul29-decrease-25',
            'fed-jul29-decrease-50-plus'
        )
          AND source_name = 'fed_fomc'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 50
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND prepare_from =
              TIMESTAMPTZ '2026-07-29 17:55:00+00'
          AND expires_at =
              TIMESTAMPTZ '2026-07-29 18:20:00+00'
          AND status = 'DISABLED'
    ) <> 5 THEN
        RAISE EXCEPTION 'FED July execution profile set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'fed-jul29-no-change',
            'fed-jul29-increase-25',
            'fed-jul29-increase-50-plus',
            'fed-jul29-decrease-25',
            'fed-jul29-decrease-50-plus'
        )
          AND source_reference NOT LIKE
              'https://polymarket.com/event/fed-decision-in-july-181/%'
    ) <> 0 THEN
        RAISE EXCEPTION 'FED July market URL set mismatch';
    END IF;

    IF (
        SELECT count(DISTINCT condition_id)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'fed-jul29-no-change',
            'fed-jul29-increase-25',
            'fed-jul29-increase-50-plus',
            'fed-jul29-decrease-25',
            'fed-jul29-decrease-50-plus'
        )
    ) <> 5 THEN
        RAISE EXCEPTION 'FED July condition set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE profile_key IN (
            'fed-jul29-no-change',
            'fed-jul29-increase-25',
            'fed-jul29-increase-50-plus',
            'fed-jul29-decrease-25',
            'fed-jul29-decrease-50-plus'
        )
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND preflight_at =
              TIMESTAMPTZ '2026-07-29 17:30:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-29 17:55:00+00'
          AND deactivate_at =
              TIMESTAMPTZ '2026-07-29 18:20:00+00'
          AND state = 'PENDING'
    ) <> 5 THEN
        RAISE EXCEPTION 'FED July schedule set mismatch';
    END IF;

    SELECT SUM(
        quantity * GREATEST(yes_desired_price, no_desired_price)
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'fed-jul29-no-change',
        'fed-jul29-increase-25',
        'fed-jul29-increase-50-plus',
        'fed-jul29-decrease-25',
        'fed-jul29-decrease-50-plus'
    );

    IF reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'FED July reviewed notional exceeds 1000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'fed:fomc:2026-07-29:%'
    ) THEN
        RAISE EXCEPTION 'FED July execution claim must not exist';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE source_name = 'fed_fomc'
          AND status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'FED execution profile must not be enabled';
    END IF;
END
$verification$;

ROLLBACK;
