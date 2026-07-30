-- Read-only verification of the additive timing-contract schema.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'earnings_release_catalog'
          AND column_name IN (
              'earliest_expected_release_at',
              'timing_basis',
              'timing_confidence',
              'activation_safety_lead_seconds',
              'timing_source_url'
          )
    ) <> 5 THEN
        RAISE EXCEPTION 'earnings release timing schema is incomplete';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_profile_schedules'
          AND column_name IN (
              'earliest_signal_at',
              'activation_safety_lead_seconds',
              'timing_basis',
              'timing_source_url',
              'timing_contract_version'
          )
    ) <> 5 THEN
        RAISE EXCEPTION 'schedule timing schema is incomplete';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'earnings_release_catalog'::regclass
          AND conname = 'earnings_release_catalog_timing_contract_check'
    ) OR NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'resolution_profile_schedules'::regclass
          AND conname =
              'resolution_profile_schedules_timing_contract_check'
    ) THEN
        RAISE EXCEPTION 'timing contract constraint is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = 'resolution_profile_schedules'::regclass
          AND tgname = 'trg_resolution_schedule_timing_contract'
          AND NOT tgisinternal
          AND tgenabled <> 'D'
    ) THEN
        RAISE EXCEPTION 'AUTO_LIVE timing trigger is missing or disabled';
    END IF;
END
$verification$;

ROLLBACK;
