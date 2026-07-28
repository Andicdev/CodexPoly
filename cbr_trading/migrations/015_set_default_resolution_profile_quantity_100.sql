-- Change only the operator-managed default for profiles created in future.
-- Existing execution profiles are intentionally left unchanged.

DO $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM resolution_profile_templates
        WHERE template_key = 'default'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity IN (50, 100)
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
    ) THEN
        RAISE EXCEPTION
            'default resolution profile template cannot be upgraded safely';
    END IF;
END
$guard$;

UPDATE resolution_profile_templates
SET
    quantity = 100,
    metadata = metadata || jsonb_build_object(
        'purpose', 'operator_default',
        'quantity_policy', '100_shares',
        'updated_by_migration',
        '015_set_default_resolution_profile_quantity_100'
    ),
    updated_at = now()
WHERE template_key = 'default';

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_templates
        WHERE template_key = 'default'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND metadata ->> 'quantity_policy' = '100_shares'
    ) <> 1 THEN
        RAISE EXCEPTION
            'default resolution profile template upgrade failed';
    END IF;
END
$verify$;
