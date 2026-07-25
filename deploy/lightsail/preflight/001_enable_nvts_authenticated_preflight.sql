-- Temporarily open exactly one production profile for authenticated preflight.
-- This script does not submit orders and must be followed by the restore SQL.

BEGIN;

DO $enable$
DECLARE
    changed_rows integer;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'another execution profile is already enabled';
    END IF;

    UPDATE resolution_execution_profiles
    SET
        status = 'ENABLED',
        prepare_from = now() - interval '5 minutes',
        expires_at = now() + interval '45 minutes',
        updated_at = now()
    WHERE profile_key = 'earnings-nvts-2026q2'
      AND scope_id = 'earnings:NVTS:2026Q2'
      AND account_name = 'abccbaq'
      AND status = 'DISABLED'
      AND yes_desired_price = 0.999
      AND no_desired_price = 0.999
      AND quantity = 50
      AND prepare_from = TIMESTAMPTZ '2026-07-27 19:00:00+00'
      AND expires_at = TIMESTAMPTZ '2026-07-28 03:00:00+00';

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION 'NVTS preflight profile did not match safe baseline';
    END IF;
END
$enable$;

COMMIT;
