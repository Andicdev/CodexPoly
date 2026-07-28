-- Read-only verification for the non-executable July 29 research backlog.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE ticker IN (
            'WING',
            'ARCC',
            'IART',
            'GRMN',
            'CBRE',
            'PAG',
            'ETSY',
            'SONO',
            'ARM',
            'WAY',
            'EA',
            'MGM',
            'ORLY',
            'TDOC',
            'CMG',
            'CVNA'
        )
          AND release_date = DATE '2026-07-29'
          AND schedule_status = 'ESTIMATED'
          AND integration_status = 'RESEARCH_PENDING'
          AND document_format = 'UNKNOWN'
          AND metric_options ->> 'comparison_op' = '>'
          AND metric_options ->> 'primary_basis' = 'diluted'
          AND metric_options ? 'market_slug'
          AND metric_options ? 'condition_id'
    ) <> 16 THEN
        RAISE EXCEPTION 'July 29 research backlog mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE metadata ->> 'ticker' IN (
            'WING',
            'ARCC',
            'IART',
            'GRMN',
            'CBRE',
            'PAG',
            'ETSY',
            'SONO',
            'ARM',
            'WAY',
            'EA',
            'MGM',
            'ORLY',
            'TDOC',
            'CMG',
            'CVNA'
        )
    ) THEN
        RAISE EXCEPTION 'research backlog unexpectedly has profiles';
    END IF;
END
$verification$;

ROLLBACK;
