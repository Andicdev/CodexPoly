-- Temporarily enable exactly one checked-in MSTR profile for preflight.

BEGIN;

LOCK TABLE resolution_execution_profiles
    IN SHARE ROW EXCLUSIVE MODE;

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

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'mstr-btc:2026-07-21:2026-07-27:%'
    ) THEN
        RAISE EXCEPTION 'an MSTR execution claim already exists';
    END IF;

    UPDATE resolution_execution_profiles
    SET
        status = 'ENABLED',
        prepare_from = now() - interval '5 minutes',
        updated_at = now()
    WHERE profile_key = 'mstr-jul21-27-purchase-over-1000'
      AND scope_id =
          'mstr-btc:2026-07-21:2026-07-27:purchase-over-1000'
      AND source_name = 'mstr_btc_resolution'
      AND source_reference =
          'https://polymarket.com/event/microstrategy-announces-1000-btc-purchase-july-21-27'
      AND account_name = 'abccbaq'
      AND condition_id =
          '0x53e75dd47cd2e9076955ca4e8e8827c5718dd1e9566d49d74a831b0465501ec1'
      AND yes_desired_price = 0.999
      AND no_desired_price = 0.999
      AND quantity = 50
      AND lifecycle_kind = 'reprice_on_tick_change'
      AND old_tick = 0.01
      AND new_tick = 0.001
      AND max_reprices = 1
      AND prepare_from = TIMESTAMPTZ '2026-07-27 06:00:00+00'
      AND expires_at = TIMESTAMPTZ '2026-07-28 04:00:00+00'
      AND status = 'DISABLED';

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION 'purchase-over-1000 profile baseline mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
          AND prepare_from <= now()
          AND expires_at >= now()
    ) <> 1 THEN
        RAISE EXCEPTION 'expected exactly one enabled in-window profile';
    END IF;
END
$enable$;

COMMIT;
