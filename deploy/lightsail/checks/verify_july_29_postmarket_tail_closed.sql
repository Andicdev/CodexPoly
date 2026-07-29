-- Fail-closed verification for the residual July 29 POST_MARKET profiles.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-hood-2026q2'
          AND schedule.state = 'COMPLETED'
          AND profile.status = 'DISABLED'
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->> 'investigation_required' =
              'true'
    ) <> 1 THEN
        RAISE EXCEPTION 'HOOD is not safely closed';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:HOOD:2026Q2'
          AND ticker = 'HOOD'
          AND provider = 'sec'
          AND value = 0.62
          AND status IN ('VALIDATED', 'EMITTED')
    ) <> 1 OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:HOOD:2026Q2'
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) THEN
        RAISE EXCEPTION 'HOOD evidence preservation failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-ea-2027q1'
          AND schedule.state = 'BLOCKED'
          AND profile.status = 'DISABLED'
          AND schedule.last_error_code =
              'official_schedule_unconfirmed'
    ) <> 1 OR EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:EA:2027Q1'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:EA:2027Q1'
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) THEN
        RAISE EXCEPTION 'EA is not safely blocked';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE event_key IN (
            'postmarket-close:earnings-hood-2026q2:2026-07-29',
            'schedule-block:earnings-ea-2027q1:2026-07-29'
        )
    ) <> 2 THEN
        RAISE EXCEPTION 'Tail lifecycle audit events are incomplete';
    END IF;
END
$verification$;

ROLLBACK;
