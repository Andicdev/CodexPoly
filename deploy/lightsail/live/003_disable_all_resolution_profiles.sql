-- Fail-closed database disarm. This does not cancel remote orders and does
-- not stop a worker that already holds a profile in memory. Stop the live
-- resolution worker first, then apply this SQL, then start the base stack.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';

LOCK TABLE resolution_execution_profiles
    IN SHARE ROW EXCLUSIVE MODE;

UPDATE resolution_execution_profiles
SET
    status = 'DISABLED',
    updated_at = now()
WHERE status <> 'DISABLED';

DO $verify$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE status <> 'DISABLED'
    ) THEN
        RAISE EXCEPTION 'an execution profile remains enabled';
    END IF;
END
$verify$;

COMMIT;
