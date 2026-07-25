-- Restore the checked-in NVTS window and fail closed after preflight.

BEGIN;

DO $restore$
DECLARE
    changed_rows integer;
BEGIN
    UPDATE resolution_execution_profiles
    SET
        status = 'DISABLED',
        prepare_from = TIMESTAMPTZ '2026-07-27 19:00:00+00',
        expires_at = TIMESTAMPTZ '2026-07-28 03:00:00+00',
        updated_at = now()
    WHERE profile_key = 'earnings-nvts-2026q2'
      AND scope_id = 'earnings:NVTS:2026Q2'
      AND account_name = 'abccbaq';

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION 'NVTS profile could not be restored';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'an execution profile remains enabled';
    END IF;
END
$restore$;

COMMIT;
