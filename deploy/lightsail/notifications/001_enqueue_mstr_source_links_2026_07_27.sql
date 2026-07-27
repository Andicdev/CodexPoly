-- One-time idempotent follow-up for the MSTR event whose original Telegram
-- text was truncated by the former 240-character log-safe limit.
-- The append-only MSTR source audit is read only; no trading state is touched.

BEGIN;

DO $guard$
BEGIN
    IF (
        SELECT count(*)
        FROM mstr_btc_source_events AS event
        JOIN mstr_btc_fact_candidates AS fact
          ON fact.source_event_id = event.id
        JOIN mstr_btc_processing_results AS result
          ON result.source_event_id = event.id
         AND result.fact_candidate_id = fact.id
        WHERE event.scope_id = 'mstr-btc:2026-07-21:2026-07-27'
          AND event.provider = 'sec'
          AND result.status = 'ACCEPTED'
    ) <> 1 THEN
        RAISE EXCEPTION 'expected exactly one accepted MSTR SEC event';
    END IF;
END
$guard$;

INSERT INTO source_notification_outbox (
    notification_key,
    source_name,
    scope_id,
    event_kind,
    message_text,
    source_url,
    available_at
)
SELECT
    'mstr-btc:source-links-recovery:' || event.id::text,
    'mstr_btc_resolution',
    event.scope_id,
    'mstr_btc_source_links',
    'CodexPoly: MSTR source links'
        || E'\nProvider: ' || event.provider
        || E'\nSource document: ' || event.source_url
        || CASE
            WHEN event.filing_url <> event.source_url
            THEN E'\nFiling: ' || event.filing_url
            ELSE ''
        END,
    event.source_url,
    now()
FROM mstr_btc_source_events AS event
JOIN mstr_btc_fact_candidates AS fact
  ON fact.source_event_id = event.id
JOIN mstr_btc_processing_results AS result
  ON result.source_event_id = event.id
 AND result.fact_candidate_id = fact.id
WHERE event.scope_id = 'mstr-btc:2026-07-21:2026-07-27'
  AND event.provider = 'sec'
  AND result.status = 'ACCEPTED'
ON CONFLICT (notification_key) DO NOTHING;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM source_notification_outbox
        WHERE notification_key LIKE
            'mstr-btc:source-links-recovery:%'
          AND scope_id = 'mstr-btc:2026-07-21:2026-07-27'
          AND source_name = 'mstr_btc_resolution'
          AND event_kind = 'mstr_btc_source_links'
          AND position(source_url IN message_text) > 0
    ) <> 1 THEN
        RAISE EXCEPTION 'MSTR source-link follow-up mismatch';
    END IF;
END
$verify$;

COMMIT;
