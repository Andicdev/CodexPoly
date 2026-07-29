-- Verify all July 29 POST_MARKET earnings profiles are no longer live.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles AS profile
        JOIN resolution_profile_schedules AS schedule
          ON schedule.profile_key = profile.profile_key
        WHERE schedule.metadata ->> 'live_block' = 'POST_MARKET'
          AND (
              schedule.metadata ->> 'block_id' LIKE
                  '2026-07-29-%-post-market'
              OR schedule.metadata ->> 'block_id' =
                  '2026-07-29-way-post-market'
          )
          AND profile.status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'July 29 POST_MARKET profile remains enabled';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key IN (
            'earnings-hood-2026q2',
            'earnings-ea-2027q1',
            'earnings-msft-2026q4'
        )
          AND profile.status = 'DISABLED'
          AND (
              (
                  schedule.profile_key = 'earnings-ea-2027q1'
                  AND schedule.state = 'BLOCKED'
                  AND schedule.last_error_code =
                      'official_schedule_unconfirmed'
              )
              OR (
                  schedule.profile_key IN (
                      'earnings-hood-2026q2',
                      'earnings-msft-2026q4'
                  )
                  AND schedule.state = 'COMPLETED'
              )
          )
    ) <> 3 THEN
        RAISE EXCEPTION 'July 29 tail lifecycle state mismatch';
    END IF;
END
$verification$;

ROLLBACK;
