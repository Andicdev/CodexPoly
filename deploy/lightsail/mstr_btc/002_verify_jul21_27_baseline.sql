-- Read-only invariant for the MSTR July 21-27 baseline.
-- The runner returns only success or failure, never database rows.

BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    pinned_id bigint;
BEGIN
    IF to_regclass('mstr_btc_holdings_state') IS NULL THEN
        RAISE EXCEPTION 'MSTR holdings schema is not ready';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = 'mstr_btc_holdings_state'::regclass
          AND tgname = 'trg_mstr_btc_holdings_state_append_only'
          AND NOT tgisinternal
    ) THEN
        RAISE EXCEPTION 'MSTR holdings append-only trigger is missing';
    END IF;

    IF (
        SELECT count(*)
        FROM mstr_btc_holdings_state
        WHERE provider = 'sec'
          AND provider_event_id = '0001193125-26-308369'
    ) <> 1 THEN
        RAISE EXCEPTION 'expected exactly one July 20 MSTR baseline';
    END IF;

    SELECT id
    INTO pinned_id
    FROM mstr_btc_holdings_state
    WHERE validation_status = 'VALIDATED'
      AND as_of < TIMESTAMPTZ '2026-07-21 04:00:00+00'
      AND observed_at < TIMESTAMPTZ '2026-07-21 04:00:00+00'
    ORDER BY as_of DESC, observed_at DESC, id DESC
    LIMIT 1;

    IF pinned_id IS NULL THEN
        RAISE EXCEPTION 'no validated pre-window MSTR baseline';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM mstr_btc_holdings_state
        WHERE id = pinned_id
          AND holdings_btc = 843775
          AND as_of =
              TIMESTAMPTZ '2026-07-19 00:00:00+00'
          AND observed_at =
              TIMESTAMPTZ '2026-07-20 12:00:16+00'
          AND provider = 'sec'
          AND provider_event_id = '0001193125-26-308369'
          AND validation_status = 'VALIDATED'
    ) THEN
        RAISE EXCEPTION 'pinned MSTR baseline does not match';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM mstr_btc_holdings_state
        WHERE validation_status = 'VALIDATED'
          AND (
              as_of >= TIMESTAMPTZ '2026-07-21 04:00:00+00'
              OR observed_at >=
                  TIMESTAMPTZ '2026-07-21 04:00:00+00'
          )
          AND id = pinned_id
    ) THEN
        RAISE EXCEPTION 'late observation was selected as baseline';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE scope_id LIKE 'mstr-btc:%'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'mstr-btc:%'
    ) THEN
        RAISE EXCEPTION 'MSTR execution state exists during baseline-only stage';
    END IF;
END
$verify$;

ROLLBACK;
