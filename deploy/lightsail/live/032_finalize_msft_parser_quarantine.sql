-- Close the residual MSFT profile after the official result was quarantined.
-- Preserve source events and parser evidence for the post-market audit.

BEGIN;

DO $guard$
BEGIN
    PERFORM schedule.id
    FROM resolution_profile_schedules AS schedule
    JOIN resolution_execution_profiles AS profile
      ON profile.profile_key = schedule.profile_key
    WHERE schedule.profile_key = 'earnings-msft-2026q4'
    FOR UPDATE OF schedule, profile;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-msft-2026q4'
          AND profile.scope_id = 'earnings:MSFT:2026Q4'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-29-msft-post-market'
          AND schedule.state NOT IN ('COMPLETED', 'EXPIRED')
          AND profile.status IN ('ENABLED', 'DISABLED')
    ) <> 1 THEN
        RAISE EXCEPTION 'MSFT lifecycle close guard failed';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_source_events
        WHERE scope_id = 'earnings:MSFT:2026Q4'
          AND status = 'QUARANTINED'
          AND error = 'conflicting_microsoft_gaap_eps_values'
    ) THEN
        RAISE EXCEPTION 'MSFT parser quarantine evidence is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:MSFT:2026Q4'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:MSFT:2026Q4'
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) OR EXISTS (
        SELECT 1
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        WHERE profile.profile_key = 'earnings-msft-2026q4'
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
    ) THEN
        RAISE EXCEPTION 'MSFT unexpected live execution evidence exists';
    END IF;
END
$guard$;

INSERT INTO resolution_profile_schedule_events (
    event_key,
    schedule_id,
    schedule_key,
    profile_key,
    previous_state,
    next_state,
    event_kind,
    reason_code,
    metadata
)
SELECT
    'postmarket-close:earnings-msft-2026q4:2026-07-29',
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.state,
    'COMPLETED',
    'POST_EVENT_RECONCILIATION_COMPLETED',
    'official_result_parser_quarantined',
    jsonb_build_object(
        'block_id', '2026-07-29-msft-post-market',
        'parser_error', 'conflicting_microsoft_gaap_eps_values',
        'validated_fact_present', false,
        'live_execution_claim_present', false,
        'order_group_present', false,
        'investigation_required', true,
        'existing_orders_left_unchanged', true
    )
FROM resolution_profile_schedules AS schedule
WHERE schedule.profile_key = 'earnings-msft-2026q4'
  AND schedule.state NOT IN ('COMPLETED', 'EXPIRED')
ON CONFLICT (event_key) DO NOTHING;

UPDATE resolution_execution_profiles
SET status = 'DISABLED', updated_at = now()
WHERE profile_key = 'earnings-msft-2026q4'
  AND status = 'ENABLED';

UPDATE resolution_profile_schedules
SET
    state = 'COMPLETED',
    last_error_code = NULL,
    metadata = metadata || jsonb_build_object(
        'completion_reason', 'official_result_parser_quarantined',
        'parser_error', 'conflicting_microsoft_gaap_eps_values',
        'validated_fact_present', false,
        'live_execution_claim_present', false,
        'order_group_present', false,
        'investigation_required', true
    ),
    updated_at = now()
WHERE profile_key = 'earnings-msft-2026q4'
  AND state NOT IN ('COMPLETED', 'EXPIRED');

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-msft-2026q4'
          AND schedule.state = 'COMPLETED'
          AND profile.status = 'DISABLED'
          AND schedule.metadata ->> 'parser_error' =
              'conflicting_microsoft_gaap_eps_values'
          AND schedule.metadata ->> 'investigation_required' =
              'true'
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE event_key =
              'postmarket-close:earnings-msft-2026q4:2026-07-29'
          AND next_state = 'COMPLETED'
          AND reason_code = 'official_result_parser_quarantined'
    ) <> 1 THEN
        RAISE EXCEPTION 'MSFT lifecycle close verification failed';
    END IF;
END
$verify$;

COMMIT;
