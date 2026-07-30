-- Additive timing contract for release-driven AUTO_LIVE schedules.
-- Existing schedules remain version 0 for backward compatibility. New
-- AUTO_LIVE inserts/transitions and activate_at changes must use version 1.

ALTER TABLE resolution_profile_schedules
    ADD COLUMN IF NOT EXISTS earliest_signal_at timestamptz,
    ADD COLUMN IF NOT EXISTS activation_safety_lead_seconds integer,
    ADD COLUMN IF NOT EXISTS timing_basis text,
    ADD COLUMN IF NOT EXISTS timing_source_url text,
    ADD COLUMN IF NOT EXISTS timing_contract_version smallint
        NOT NULL DEFAULT 0;

DO $schedule_constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'resolution_profile_schedules'::regclass
          AND conname =
              'resolution_profile_schedules_timing_contract_check'
    ) THEN
        ALTER TABLE resolution_profile_schedules
            ADD CONSTRAINT
                resolution_profile_schedules_timing_contract_check
            CHECK (
                (
                    timing_contract_version = 0
                    AND earliest_signal_at IS NULL
                    AND activation_safety_lead_seconds IS NULL
                    AND timing_basis IS NULL
                    AND timing_source_url IS NULL
                ) OR (
                    timing_contract_version = 1
                    AND earliest_signal_at IS NOT NULL
                    AND activation_safety_lead_seconds
                        BETWEEN 0 AND 86400
                    AND timing_basis IN (
                        'OFFICIAL_EXACT',
                        'OFFICIAL_WINDOW',
                        'HISTORICAL_PATTERN',
                        'SESSION_FLOOR'
                    )
                    AND timing_source_url LIKE 'https://%'
                    AND activate_at <= earliest_signal_at
                        - activation_safety_lead_seconds
                            * interval '1 second'
                )
            );
    END IF;
END
$schedule_constraints$;

CREATE OR REPLACE FUNCTION enforce_resolution_schedule_timing_contract()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.automation_mode <> 'AUTO_LIVE' THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' AND NEW.timing_contract_version <> 1 THEN
        RAISE EXCEPTION
            'AUTO_LIVE requires a versioned earliest-signal timing contract';
    END IF;

    IF TG_OP = 'UPDATE'
       AND (
           OLD.automation_mode IS DISTINCT FROM NEW.automation_mode
           OR OLD.activate_at IS DISTINCT FROM NEW.activate_at
       )
       AND NEW.timing_contract_version <> 1
    THEN
        RAISE EXCEPTION
            'AUTO_LIVE requires a versioned earliest-signal timing contract';
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS trg_resolution_schedule_timing_contract
    ON resolution_profile_schedules;

CREATE TRIGGER trg_resolution_schedule_timing_contract
BEFORE INSERT OR UPDATE
ON resolution_profile_schedules
FOR EACH ROW
EXECUTE FUNCTION enforce_resolution_schedule_timing_contract();
