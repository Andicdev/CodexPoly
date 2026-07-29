-- Ensure the separately reviewed FED source remains non-trading during this
-- lifecycle rollout. The check returns no profile, market, claim, or order
-- data and does not require the five shadow definitions to exist.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE source_name = 'fed_fomc'
          AND status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION
            'FED profile was enabled during lifecycle rollout';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE profile.source_name = 'fed_fomc'
          AND schedule.state = 'ACTIVE'
    ) THEN
        RAISE EXCEPTION
            'FED schedule became active during lifecycle rollout';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'fed:fomc:2026-07-29:%'
    ) THEN
        RAISE EXCEPTION
            'FED execution claim exists during lifecycle rollout';
    END IF;
END
$verification$;

ROLLBACK;
