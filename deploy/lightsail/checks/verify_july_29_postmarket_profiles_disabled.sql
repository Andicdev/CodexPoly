-- Read-only guard: no July 29 POST_MARKET earnings profile is enabled.

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
END
$verification$;

ROLLBACK;
