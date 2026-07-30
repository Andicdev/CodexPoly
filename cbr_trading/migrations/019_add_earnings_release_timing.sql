-- Additive release-timing evidence for the research catalog.

ALTER TABLE earnings_release_catalog
    ADD COLUMN IF NOT EXISTS earliest_expected_release_at timestamptz,
    ADD COLUMN IF NOT EXISTS timing_basis text,
    ADD COLUMN IF NOT EXISTS timing_confidence text,
    ADD COLUMN IF NOT EXISTS activation_safety_lead_seconds integer,
    ADD COLUMN IF NOT EXISTS timing_source_url text;

DO $catalog_constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'earnings_release_catalog'::regclass
          AND conname = 'earnings_release_catalog_timing_contract_check'
    ) THEN
        ALTER TABLE earnings_release_catalog
            ADD CONSTRAINT earnings_release_catalog_timing_contract_check
            CHECK (
                (
                    earliest_expected_release_at IS NULL
                    AND timing_basis IS NULL
                    AND timing_confidence IS NULL
                    AND activation_safety_lead_seconds IS NULL
                    AND timing_source_url IS NULL
                ) OR (
                    earliest_expected_release_at IS NOT NULL
                    AND timing_basis IN (
                        'OFFICIAL_EXACT',
                        'OFFICIAL_WINDOW',
                        'HISTORICAL_PATTERN',
                        'SESSION_FLOOR'
                    )
                    AND timing_confidence IN ('HIGH', 'MEDIUM', 'LOW')
                    AND activation_safety_lead_seconds BETWEEN 0 AND 86400
                    AND timing_source_url LIKE 'https://%'
                    AND (
                        scheduled_release_at IS NULL
                        OR earliest_expected_release_at
                            <= scheduled_release_at
                    )
                    AND (
                        conference_call_at IS NULL
                        OR earliest_expected_release_at
                            <= conference_call_at
                    )
                )
            );
    END IF;
END
$catalog_constraints$;

CREATE INDEX IF NOT EXISTS ix_earnings_release_catalog_earliest
    ON earnings_release_catalog (
        earliest_expected_release_at,
        ticker
    )
    WHERE earliest_expected_release_at IS NOT NULL;
