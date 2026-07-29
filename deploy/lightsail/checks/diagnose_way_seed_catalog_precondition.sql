-- Read-only production diagnostic for the optional public WAY catalog row.
BEGIN;

SET TRANSACTION READ ONLY;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $diagnostic$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'WAY:2026-07-29'
    ) > 1 OR EXISTS (
        SELECT 1
        FROM earnings_release_catalog
        WHERE event_key = 'WAY:2026-07-29'
          AND (
              ticker <> 'WAY'
              OR integration_status NOT IN (
                  'RESEARCH_PENDING',
                  'PARSER_ONLY'
              )
          )
    ) THEN
        RAISE EXCEPTION 'WAY catalog precondition is not satisfied';
    END IF;
END
$diagnostic$;

ROLLBACK;
