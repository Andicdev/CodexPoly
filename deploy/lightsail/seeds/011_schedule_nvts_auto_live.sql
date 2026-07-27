-- Arm the separately approved NVTS profile for the July 27 live window.
-- The profile remains DISABLED until authenticated readiness and the exact
-- activation time are both reached.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';

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
SELECT
    'schedule:earnings-nvts-2026q2',
    profile.profile_key,
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
FROM resolution_execution_profiles AS profile
JOIN earnings_market_rules AS rule
  ON rule.scope_id = profile.scope_id
JOIN trading_account_metadata AS account
  ON account.account_name = profile.account_name
JOIN resolution_runtime_heartbeats AS heartbeat
  ON heartbeat.runtime_key = 'hosted-resolution'
WHERE clock_timestamp() <
          TIMESTAMPTZ '2026-07-27 18:45:00+00'
  AND profile.profile_key = 'earnings-nvts-2026q2'
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
  AND profile.status = 'DISABLED'
  AND rule.rule_key = 'nvts-2026q2-nongaap-eps-neg0pt04'
  AND rule.ticker = 'NVTS'
  AND rule.metric_kind = 'non_gaap_eps'
  AND rule.comparison_op = '>'
  AND rule.strike = -0.04
  AND rule.rounding_places = 2
  AND rule.condition_id = profile.condition_id
  AND rule.status IN ('SHADOW', 'WATCHING')
  AND account.wallet_address =
      '0x343FDd2bf9272Bd12cffBFE510f3969F57E36Df2'
  AND account.venue = 'polymarket_clob'
  AND account.signature_type = 2
  AND account.is_active = true
  AND heartbeat.mode = 'live'
  AND heartbeat.supervision_enabled
  AND heartbeat.trading_enabled
  AND heartbeat.last_seen_at >
      clock_timestamp() - interval '15 seconds'
  AND NOT EXISTS (
      SELECT 1
      FROM resolution_execution_profiles
      WHERE status = 'ENABLED'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM earnings_fact_candidates
      WHERE scope_id = 'earnings:NVTS:2026Q2'
        AND status = 'VALIDATED'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM resolution_execution_claims
      WHERE scope_id = 'earnings:NVTS:2026Q2'
  )
  AND NOT EXISTS (
      SELECT 1
      FROM resolution_order_groups
      WHERE account_name = 'abccbaq'
        AND condition_id =
            '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d'
        AND status IN ('ACTIVE', 'REPRICING')
  )
  AND NOT EXISTS (
      SELECT 1
      FROM resolution_profile_schedules
      WHERE profile_key = 'earnings-nvts-2026q2'
         OR schedule_key = 'schedule:earnings-nvts-2026q2'
  )
  AND (
      profile.quantity * GREATEST(
          profile.yes_desired_price,
          profile.no_desired_price
      )
      + COALESCE(
          (
              SELECT
                  SUM(
                      scheduled_profile.quantity * GREATEST(
                          scheduled_profile.yes_desired_price,
                          scheduled_profile.no_desired_price
                      )
                  )
              FROM resolution_profile_schedules AS schedule
              JOIN resolution_execution_profiles AS scheduled_profile
                ON scheduled_profile.profile_key = schedule.profile_key
              WHERE schedule.automation_mode = 'AUTO_LIVE'
                AND schedule.state NOT IN ('BLOCKED', 'EXPIRED')
          ),
          0
      )
  ) <= 1000;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key =
                  'schedule:earnings-nvts-2026q2'
          AND schedule.profile_key = 'earnings-nvts-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-27 18:45:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-27 19:00:00+00'
          AND schedule.deactivate_at =
              TIMESTAMPTZ '2026-07-28 03:00:00+00'
          AND schedule.state = 'PENDING'
          AND profile.status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'NVTS AUTO_LIVE schedule was not safely created';
    END IF;
END
$verify$;

COMMIT;
