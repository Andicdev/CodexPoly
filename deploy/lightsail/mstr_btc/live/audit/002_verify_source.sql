BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM mstr_btc_source_events
        WHERE scope_id = 'mstr-btc:2026-07-21:2026-07-27'
          AND provider = 'sec'
          AND ticker = 'MSTR'
          AND form_type = '8-K'
    ) <> 1 OR (
        SELECT count(*)
        FROM mstr_btc_fact_candidates
        WHERE scope_id = 'mstr-btc:2026-07-21:2026-07-27'
          AND provider = 'sec'
          AND holdings_before_btc = 843775
          AND holdings_after_btc = 843775
          AND net_change_btc = 0
          AND acquired_btc = 0
          AND sold_btc IS NULL
          AND validation_status = 'VALIDATED'
    ) <> 1 OR (
        SELECT count(*)
        FROM mstr_btc_processing_results AS result
        JOIN mstr_btc_source_events AS event
          ON event.id = result.source_event_id
        WHERE event.scope_id = 'mstr-btc:2026-07-21:2026-07-27'
          AND result.status = 'ACCEPTED'
          AND result.fact_candidate_id IS NOT NULL
    ) <> 1 THEN
        RAISE EXCEPTION 'MSTR source invariant failed';
    END IF;
END
$verify$;

ROLLBACK;
