-- Staging-only transactional proof that legacy schedules remain readable
-- while a new AUTO_LIVE transition/change without version 1 is rejected.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $verification$
DECLARE
    target_id bigint;
    target_mode text;
    failure_message text;
BEGIN
    SELECT id, automation_mode
    INTO target_id, target_mode
    FROM resolution_profile_schedules
    WHERE timing_contract_version = 0
      AND state IN ('PENDING', 'READY', 'ACTIVE')
    ORDER BY id
    LIMIT 1;

    IF target_id IS NULL THEN
        RAISE EXCEPTION 'no legacy schedule is available for trigger test';
    END IF;

    BEGIN
        IF target_mode = 'AUTO_LIVE' THEN
            UPDATE resolution_profile_schedules
            SET activate_at = activate_at - interval '1 second'
            WHERE id = target_id;
        ELSE
            UPDATE resolution_profile_schedules
            SET automation_mode = 'AUTO_LIVE'
            WHERE id = target_id;
        END IF;
        RAISE EXCEPTION 'timing trigger accepted an unsafe transition';
    EXCEPTION
        WHEN raise_exception THEN
            GET STACKED DIAGNOSTICS failure_message = MESSAGE_TEXT;
            IF failure_message <>
                'AUTO_LIVE requires a versioned earliest-signal timing contract'
            THEN
                RAISE EXCEPTION 'timing trigger returned an unexpected result';
            END IF;
    END;
END
$verification$;

ROLLBACK;
