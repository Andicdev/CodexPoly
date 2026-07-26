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
    WHERE profile_key = 'mstr-jul21-27-sale-any'
      AND scope_id = 'mstr-btc:2026-07-21:2026-07-27:sale-any'
      AND source_name = 'mstr_btc_resolution'
      AND source_reference =
          'https://polymarket.com/event/will-microstrategy-announce-selling-any-bitcoin-july-21-27'
      AND account_name = 'abccbaq'
      AND condition_id =
          '0xc937afbe3ce062c934d2922c313a8990907f1d382a55e8ee56d36a5b0359500b'
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
        RAISE EXCEPTION 'sale-any profile did not match safe baseline';
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
