-- Fail closed unless restarting hosted workers cannot interrupt an active or
-- imminently activating live profile. No profile, claim, or order data is
-- returned.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION
            'worker restart blocked by enabled execution profile';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules
        WHERE state = 'ACTIVE'
    ) THEN
        RAISE EXCEPTION
            'worker restart blocked by active profile schedule';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules
        WHERE state IN ('PENDING', 'PREFLIGHTING', 'READY')
          AND activate_at <= now() + interval '15 minutes'
          AND deactivate_at > now()
    ) THEN
        RAISE EXCEPTION
            'worker restart blocked by imminent profile schedule';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE status = 'PENDING'
    ) THEN
        RAISE EXCEPTION
            'worker restart blocked by pending execution claim';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION
            'worker restart blocked by active order supervision';
    END IF;
END
$verification$;

ROLLBACK;
