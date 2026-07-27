-- Arm the separately approved NVTS profile for the July 27 live window.
-- The profile remains DISABLED until authenticated readiness and the exact
-- activation time are both reached.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';

LOCK TABLE resolution_profile_schedules
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE resolution_execution_profiles
    IN SHARE ROW EXCLUSIVE MODE;

DO $schedule$
DECLARE
    current_time timestamptz := clock_timestamp();
    changed_rows integer;
    reviewed_notional numeric;
BEGIN
    IF current_time >=
        TIMESTAMPTZ '2026-07-27 18:45:00+00'
    THEN
        RAISE EXCEPTION 'NVTS preflight lead time has elapsed';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_runtime_heartbeats
        WHERE runtime_key = 'hosted-resolution'
          AND mode = 'live'
          AND supervision_enabled
          AND trading_enabled
          AND last_seen_at > current_time - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION 'fresh live resolution heartbeat is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'an execution profile is already enabled';
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
        RAISE EXCEPTION 'NVTS source rule does not match safe baseline';
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

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules
        WHERE profile_key = 'earnings-nvts-2026q2'
           OR schedule_key = 'schedule:earnings-nvts-2026q2'
    ) THEN
        RAISE EXCEPTION 'NVTS lifecycle schedule already exists';
    END IF;

    SELECT
        COALESCE(
            SUM(
                profile.quantity * GREATEST(
                    profile.yes_desired_price,
                    profile.no_desired_price
                )
            ),
            0
        )
    INTO reviewed_notional
    FROM resolution_profile_schedules AS schedule
    JOIN resolution_execution_profiles AS profile
      ON profile.profile_key = schedule.profile_key
    WHERE schedule.automation_mode = 'AUTO_LIVE'
      AND schedule.state NOT IN ('BLOCKED', 'EXPIRED');

    SELECT
        reviewed_notional
        + profile.quantity * GREATEST(
            profile.yes_desired_price,
            profile.no_desired_price
        )
    INTO reviewed_notional
    FROM resolution_execution_profiles AS profile
    WHERE profile.profile_key = 'earnings-nvts-2026q2'
      AND profile.scope_id = 'earnings:NVTS:2026Q2'
      AND profile.source_name = 'earnings_resolution'
      AND profile.source_reference =
          'https://polymarket.com/event/nvts-quarterly-earnings-nongaap-eps-07-27-2026-neg0pt04'
      AND profile.account_name = 'abccbaq'
      AND profile.condition_id =
          '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d'
      AND profile.yes_desired_price = 0.999
      AND profile.no_desired_price = 0.999
      AND profile.quantity = 50
      AND profile.lifecycle_kind = 'reprice_on_tick_change'
      AND profile.old_tick = 0.01
      AND profile.new_tick = 0.001
      AND profile.max_reprices = 1
      AND profile.prepare_from =
          TIMESTAMPTZ '2026-07-27 19:00:00+00'
      AND profile.expires_at =
          TIMESTAMPTZ '2026-07-28 03:00:00+00'
      AND profile.status = 'DISABLED';

    IF reviewed_notional IS NULL THEN
        RAISE EXCEPTION 'NVTS execution profile does not match baseline';
    END IF;
    IF reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'reviewed aggregate notional exceeds 1000';
    END IF;

    INSERT INTO resolution_profile_schedules (
        schedule_key,
        profile_key,
        automation_mode,
        preflight_at,
        activate_at,
        deactivate_at,
        state,
        metadata
    )
    VALUES (
        'schedule:earnings-nvts-2026q2',
        'earnings-nvts-2026q2',
        'AUTO_LIVE',
        TIMESTAMPTZ '2026-07-27 18:45:00+00',
        TIMESTAMPTZ '2026-07-27 19:00:00+00',
        TIMESTAMPTZ '2026-07-28 03:00:00+00',
        'PENDING',
        jsonb_build_object(
            'seed', '011_schedule_nvts_auto_live',
            'preflight_lead_minutes', 15,
            'aggregate_notional_cap', 1000
        )
    );

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION 'expected exactly one NVTS schedule';
    END IF;
END
$schedule$;

COMMIT;
