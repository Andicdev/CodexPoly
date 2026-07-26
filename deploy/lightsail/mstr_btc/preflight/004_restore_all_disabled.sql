-- Fail closed after any sequential MSTR authenticated preflight.

BEGIN;

LOCK TABLE resolution_execution_profiles
    IN SHARE ROW EXCLUSIVE MODE;

DO $restore$
DECLARE
    changed_rows integer;
BEGIN
    UPDATE resolution_execution_profiles
    SET
        status = 'DISABLED',
        prepare_from = TIMESTAMPTZ '2026-07-27 06:00:00+00',
        expires_at = TIMESTAMPTZ '2026-07-28 04:00:00+00',
        updated_at = now()
    WHERE profile_key IN (
        'mstr-jul21-27-purchase-any',
        'mstr-jul21-27-purchase-over-1000',
        'mstr-jul21-27-sale-any'
    )
      AND source_name = 'mstr_btc_resolution'
      AND account_name = 'abccbaq';

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 3 THEN
        RAISE EXCEPTION 'MSTR profiles could not be restored';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION 'an execution profile remains enabled';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'mstr-btc:2026-07-21:2026-07-27:%'
    ) THEN
        RAISE EXCEPTION 'an MSTR execution claim exists after preflight';
    END IF;
END
$restore$;

COMMIT;
