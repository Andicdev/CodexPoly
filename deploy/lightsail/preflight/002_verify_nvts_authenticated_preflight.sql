-- Read-only verification that only the intended NVTS profile is in window.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
          AND prepare_from <= now()
          AND expires_at >= now()
    ) <> 1 THEN
        RAISE EXCEPTION 'expected exactly one enabled in-window profile';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-nvts-2026q2'
          AND scope_id = 'earnings:NVTS:2026Q2'
          AND account_name = 'abccbaq'
          AND status = 'ENABLED'
          AND prepare_from <= now()
          AND expires_at >= now()
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 50
    ) THEN
        RAISE EXCEPTION 'NVTS preflight profile is not safely enabled';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE profile_key <> 'earnings-nvts-2026q2'
          AND status <> 'DISABLED'
    ) THEN
        RAISE EXCEPTION 'another profile is not disabled';
    END IF;
END
$verify$;

ROLLBACK;
