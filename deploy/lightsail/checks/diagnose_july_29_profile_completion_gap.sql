-- Confirm the July 29 lifecycle completion gap without returning profile,
-- account, market, order, or source data.

BEGIN TRANSACTION READ ONLY;

DO $diagnostic$
DECLARE
    block_key constant text := '2026-07-29-pre-market';
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE metadata ->> 'block_id' = block_key
    ) <> 9 THEN
        RAISE EXCEPTION
            'July 29 lifecycle diagnostic schedule count failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.metadata ->> 'block_id' = block_key
          AND (
              (
                  schedule.state = 'ACTIVE'
                  AND profile.status <> 'ENABLED'
              )
              OR (
                  schedule.state <> 'ACTIVE'
                  AND profile.status = 'ENABLED'
              )
          )
    ) THEN
        RAISE EXCEPTION
            'July 29 lifecycle diagnostic status pairing failed';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN resolution_execution_claims AS claim
          ON claim.scope_id = profile.scope_id
        WHERE schedule.metadata ->> 'block_id' = block_key
          AND schedule.state IN ('ACTIVE', 'BLOCKED')
          AND claim.status = 'EXECUTED'
    ) THEN
        RAISE EXCEPTION
            'July 29 lifecycle completion gap was not reproduced';
    END IF;
END
$diagnostic$;

ROLLBACK;
