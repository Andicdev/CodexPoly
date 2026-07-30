-- Correct CI release evidence without changing any trading lifecycle state.
-- The issuer's release-details announcement says results are available no
-- later than 06:30 ET; the 08:30 ET event-card time is the conference call.

BEGIN;

DO $correction$
DECLARE
    changed_rows integer;
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'CI:2026-07-30'
          AND ticker = 'CI'
          AND release_date = DATE '2026-07-30'
          AND market_session = 'PRE_MARKET'
          AND scheduled_release_at IN (
              TIMESTAMPTZ '2026-07-30 10:30:00+00',
              TIMESTAMPTZ '2026-07-30 12:30:00+00'
          )
          AND conference_call_at =
              TIMESTAMPTZ '2026-07-30 12:30:00+00'
    ) <> 1 THEN
        RAISE EXCEPTION 'CI release catalog timing guard failed';
    END IF;

    UPDATE earnings_release_catalog
    SET
        scheduled_release_at =
            TIMESTAMPTZ '2026-07-30 10:30:00+00',
        conference_call_at =
            TIMESTAMPTZ '2026-07-30 12:30:00+00',
        schedule_source_url =
            'https://newsroom.thecignagroup.com/2026-07-07-The-Cigna-Groups-Second-Quarter-2026-Earnings-Release-Details',
        notes =
            'Issuer says results will be available no later than 06:30 ET; the 08:30 ET event is the call. The deadline is not an earliest-signal floor.',
        verified_at = now(),
        updated_at = now()
    WHERE event_key = 'CI:2026-07-30'
      AND ticker = 'CI'
      AND release_date = DATE '2026-07-30'
      AND market_session = 'PRE_MARKET'
      AND scheduled_release_at IN (
          TIMESTAMPTZ '2026-07-30 10:30:00+00',
          TIMESTAMPTZ '2026-07-30 12:30:00+00'
      )
      AND conference_call_at =
          TIMESTAMPTZ '2026-07-30 12:30:00+00';

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION 'CI release catalog correction count mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_release_catalog
        WHERE event_key = 'CI:2026-07-30'
          AND (
              scheduled_release_at <>
                  TIMESTAMPTZ '2026-07-30 10:30:00+00'
              OR conference_call_at <>
                  TIMESTAMPTZ '2026-07-30 12:30:00+00'
              OR schedule_source_url NOT LIKE
                  'https://newsroom.thecignagroup.com/%'
          )
    ) THEN
        RAISE EXCEPTION 'CI release catalog correction verification failed';
    END IF;
END
$correction$;

COMMIT;
