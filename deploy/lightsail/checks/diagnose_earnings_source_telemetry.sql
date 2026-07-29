-- Read-only breakdown of earnings discovery and processing latency.
-- Requires migration 016. Values are operational timings only.

BEGIN TRANSACTION READ ONLY;

SELECT format(
    'ticker=%s,scope=%s,provider=%s,transport=%s,fetch_route=%s,published_to_transport_ms=%s,transport_to_fetch_ms=%s,fetch_ms=%s,parse_ms=%s,fact_persist_ms=%s,transport_to_fact_ms=%s,status=%s,error=%s',
    event.ticker,
    event.scope_id,
    event.provider,
    timing.source_transport,
    coalesce(timing.document_fetch_route, 'none'),
    CASE
        WHEN timing.transport_observed_at IS NULL THEN NULL
        ELSE greatest(
            0,
            round(
                extract(epoch FROM (
                    timing.transport_observed_at - event.filed_at
                )) * 1000
            )::bigint
        )
    END,
    CASE
        WHEN timing.document_fetch_started_at IS NULL THEN NULL
        ELSE greatest(
            0,
            round(
                extract(epoch FROM (
                    timing.document_fetch_started_at
                    - timing.transport_observed_at
                )) * 1000
            )::bigint
        )
    END,
    CASE
        WHEN timing.document_fetch_completed_at IS NULL
          OR timing.document_fetch_started_at IS NULL THEN NULL
        ELSE greatest(
            0,
            round(
                extract(epoch FROM (
                    timing.document_fetch_completed_at
                    - timing.document_fetch_started_at
                )) * 1000
            )::bigint
        )
    END,
    CASE
        WHEN timing.parse_completed_at IS NULL
          OR timing.parse_started_at IS NULL THEN NULL
        ELSE greatest(
            0,
            round(
                extract(epoch FROM (
                    timing.parse_completed_at
                    - timing.parse_started_at
                )) * 1000
            )::bigint
        )
    END,
    CASE
        WHEN timing.fact_persisted_at IS NULL
          OR timing.parse_completed_at IS NULL THEN NULL
        ELSE greatest(
            0,
            round(
                extract(epoch FROM (
                    timing.fact_persisted_at
                    - timing.parse_completed_at
                )) * 1000
            )::bigint
        )
    END,
    CASE
        WHEN timing.fact_persisted_at IS NULL THEN NULL
        ELSE greatest(
            0,
            round(
                extract(epoch FROM (
                    timing.fact_persisted_at
                    - timing.transport_observed_at
                )) * 1000
            )::bigint
        )
    END,
    event.status,
    coalesce(event.error, 'none')
)
FROM earnings_source_events AS event
JOIN earnings_source_processing_telemetry AS timing
  ON timing.source_event_id = event.id
WHERE timing.transport_observed_at >= now() - interval '36 hours'
ORDER BY timing.transport_observed_at, event.id;

SELECT format(
    'ticker=%s,scope=%s,transport=%s,first_observed=%s,last_observed=%s,observations=%s,published_to_first_ms=%s',
    event.ticker,
    event.scope_id,
    observation.transport,
    observation.first_observed_at,
    observation.last_observed_at,
    observation.observation_count,
    greatest(
        0,
        round(
            extract(epoch FROM (
                observation.first_observed_at - event.filed_at
            )) * 1000
        )::bigint
    )
)
FROM earnings_source_transport_observations AS observation
JOIN earnings_source_events AS event
  ON event.id = observation.source_event_id
WHERE observation.first_observed_at >= now() - interval '36 hours'
ORDER BY
    event.scope_id,
    observation.first_observed_at,
    observation.transport;

ROLLBACK;
