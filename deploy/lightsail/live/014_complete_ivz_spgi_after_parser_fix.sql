BEGIN;

DO $guard$
DECLARE
    target_profile_key text;
BEGIN
    FOREACH target_profile_key IN ARRAY ARRAY[
        'earnings-ivz-2026q2',
        'earnings-spgi-2026q2'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM resolution_profile_schedules AS schedule
            JOIN resolution_execution_profiles AS profile
              ON profile.profile_key = schedule.profile_key
            WHERE schedule.profile_key = target_profile_key
              AND schedule.automation_mode = 'AUTO_LIVE'
              AND schedule.state = 'ACTIVE'
              AND profile.status = 'ENABLED'
        ) THEN
            RAISE EXCEPTION
                'Expected active parser-error profile missing: %',
                target_profile_key;
        END IF;
    END LOOP;

    IF (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key IN (
            'earnings:IVZ:2026Q2:2026-07-28',
            'earnings:SPGI:2026Q2:2026-07-28'
        )
          AND overall_result = 'ERROR'
          AND execution_status = 'NOT_ATTEMPTED'
          AND error_stage = 'parse'
          AND error_code = 'document_encoding_invalid'
    ) <> 2 OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:IVZ:2026Q2',
            'earnings:SPGI:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'IVZ/SPGI completion guard failed';
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
    'manual-complete:parser-error:' || lower(profile.scope_id)
        || ':2026-07-28',
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.state,
    'EXPIRED',
    'SOURCE_PROCESSING_FAILED',
    'document_encoding_invalid',
    jsonb_build_object(
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-28-pre-market',
        'fix_commit', 'ea2092f',
        'late_replay_skipped', true
    )
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
WHERE schedule.profile_key IN (
    'earnings-ivz-2026q2',
    'earnings-spgi-2026q2'
)
ON CONFLICT (event_key) DO NOTHING;

UPDATE resolution_profile_schedules
SET
    automation_mode = 'MANUAL',
    state = 'EXPIRED',
    preflight_request_id = NULL,
    preflight_requested_at = NULL,
    preflight_lease_until = NULL,
    readiness_checked_at = NULL,
    readiness_valid_until = NULL,
    readiness_evidence = '{}'::jsonb,
    last_error_code = 'document_encoding_invalid',
    metadata = metadata || jsonb_build_object(
        'completed_after_parser_error', true,
        'parser_fix_commit', 'ea2092f',
        'late_replay_skipped', true
    ),
    updated_at = now()
WHERE profile_key IN (
    'earnings-ivz-2026q2',
    'earnings-spgi-2026q2'
);

UPDATE resolution_execution_profiles
SET status = 'DISABLED', updated_at = now()
WHERE profile_key IN (
    'earnings-ivz-2026q2',
    'earnings-spgi-2026q2'
);

UPDATE earnings_market_rules
SET status = 'DISABLED', updated_at = now()
WHERE scope_id IN (
    'earnings:IVZ:2026Q2',
    'earnings:SPGI:2026Q2'
);

UPDATE earnings_release_catalog
SET schedule_status = 'REPORTED', updated_at = now()
WHERE event_key IN (
    'IVZ:2026-07-28',
    'SPGI:2026-07-28'
);

UPDATE resolution_run_journal
SET
    details = details || jsonb_build_object(
        'recovery_pending', false,
        'parser_fix_commit', 'ea2092f',
        'late_replay_skipped', true
    ),
    updated_at = now()
WHERE journal_key IN (
    'earnings:IVZ:2026Q2:2026-07-28',
    'earnings:SPGI:2026Q2:2026-07-28'
);

INSERT INTO resolution_run_journal_events (
    event_key,
    journal_id,
    event_kind,
    stage,
    event_status,
    error_code,
    details,
    occurred_at
)
SELECT
    'run-journal:' || journal.journal_key || ':run-closed',
    journal.id,
    'RUN_CLOSED',
    'parse',
    journal.overall_result,
    journal.error_code,
    jsonb_build_object(
        'parser_fix_commit', 'ea2092f',
        'late_replay_skipped', true
    ),
    now()
FROM resolution_run_journal AS journal
WHERE journal.journal_key IN (
    'earnings:IVZ:2026Q2:2026-07-28',
    'earnings:SPGI:2026Q2:2026-07-28'
)
ON CONFLICT (event_key) DO NOTHING;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key IN (
            'earnings-ivz-2026q2',
            'earnings-spgi-2026q2'
        )
          AND schedule.automation_mode = 'MANUAL'
          AND schedule.state = 'EXPIRED'
          AND schedule.last_error_code =
              'document_encoding_invalid'
          AND profile.status = 'DISABLED'
          AND rule.status = 'DISABLED'
    ) <> 2 OR (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key IN (
            'earnings:IVZ:2026Q2:2026-07-28',
            'earnings:SPGI:2026Q2:2026-07-28'
        )
          AND details ->> 'recovery_pending' = 'false'
          AND details ->> 'parser_fix_commit' = 'ea2092f'
          AND details ->> 'late_replay_skipped' = 'true'
    ) <> 2 THEN
        RAISE EXCEPTION 'IVZ/SPGI completion verification failed';
    END IF;
END
$verify$;

COMMIT;
