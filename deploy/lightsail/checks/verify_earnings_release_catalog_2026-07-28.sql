-- Fail closed without printing catalog contents through the migration runner.

DO $verification$
DECLARE
    expected_count integer := 15;
    actual_count integer;
BEGIN
    IF to_regclass('earnings_release_catalog') IS NULL THEN
        RAISE EXCEPTION 'earnings release catalog is missing';
    END IF;

    SELECT count(*)
    INTO actual_count
    FROM earnings_release_catalog
    WHERE event_key IN (
        'PYPL:2026-07-28',
        'UPS:2026-07-28',
        'HLT:2026-07-28',
        'IVZ:2026-07-28',
        'KO:2026-07-28',
        'RCL:2026-07-28',
        'BA:2026-07-28',
        'JBLU:2026-07-28',
        'SPGI:2026-07-28',
        'CZR:2026-07-28',
        'SBUX:2026-07-29',
        'CSGP:2026-07-28',
        'V:2026-07-28',
        'F:2026-07-28',
        'NXPI:2026-07-28'
    );

    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'earnings release catalog seed is incomplete';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key IN (
            'BA:2026-07-28',
            'CZR:2026-07-28',
            'CSGP:2026-07-28',
            'NXPI:2026-07-28',
            'SBUX:2026-07-29'
        )
          AND integration_status = 'PARSER_ONLY'
    ) <> 5 THEN
        RAISE EXCEPTION 'parser-only catalog classification mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_release_catalog
        WHERE event_key = 'SBUX:2026-07-29'
          AND release_date <> DATE '2026-07-29'
    ) THEN
        RAISE EXCEPTION 'Starbucks release date mismatch';
    END IF;
END
$verification$;
