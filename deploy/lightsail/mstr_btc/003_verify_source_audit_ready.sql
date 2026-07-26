BEGIN;
SET TRANSACTION READ ONLY;

DO $$
DECLARE
    trigger_count integer;
    event_count bigint;
    fact_count bigint;
    result_count bigint;
BEGIN
    IF to_regclass('mstr_btc_source_events') IS NULL
       OR to_regclass('mstr_btc_fact_candidates') IS NULL
       OR to_regclass('mstr_btc_processing_results') IS NULL THEN
        RAISE EXCEPTION 'MSTR BTC source audit tables are missing';
    END IF;

    SELECT count(*)
    INTO trigger_count
    FROM pg_trigger
    WHERE tgrelid IN (
        'mstr_btc_source_events'::regclass,
        'mstr_btc_fact_candidates'::regclass,
        'mstr_btc_processing_results'::regclass
    )
      AND tgname IN (
        'trg_mstr_btc_source_events_append_only',
        'trg_mstr_btc_fact_candidates_append_only',
        'trg_mstr_btc_processing_results_append_only'
    )
      AND NOT tgisinternal;

    IF trigger_count <> 3 THEN
        RAISE EXCEPTION 'MSTR BTC append-only trigger invariant failed';
    END IF;

    SELECT count(*) INTO event_count FROM mstr_btc_source_events;
    SELECT count(*) INTO fact_count FROM mstr_btc_fact_candidates;
    SELECT count(*) INTO result_count FROM mstr_btc_processing_results;

    IF fact_count > event_count OR result_count < fact_count THEN
        RAISE EXCEPTION 'MSTR BTC source audit count invariant failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM mstr_btc_fact_candidates AS fact
        LEFT JOIN mstr_btc_source_events AS event
          ON event.id = fact.source_event_id
        WHERE event.id IS NULL
    ) OR EXISTS (
        SELECT 1
        FROM mstr_btc_processing_results AS result
        LEFT JOIN mstr_btc_source_events AS event
          ON event.id = result.source_event_id
        WHERE event.id IS NULL
    ) THEN
        RAISE EXCEPTION 'MSTR BTC source audit contains orphan rows';
    END IF;

    IF (
        SELECT count(*)
        FROM mstr_btc_holdings_state
        WHERE validation_status = 'VALIDATED'
          AND holdings_btc = 843775
          AND as_of < '2026-07-21T04:00:00Z'::timestamptz
          AND observed_at < '2026-07-21T04:00:00Z'::timestamptz
    ) <> 1 THEN
        RAISE EXCEPTION 'MSTR BTC pinned baseline invariant failed';
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
        RAISE EXCEPTION 'MSTR BTC trading objects must remain absent';
    END IF;
END;
$$;

ROLLBACK;
