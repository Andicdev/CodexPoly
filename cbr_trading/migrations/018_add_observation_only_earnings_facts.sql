-- Keep post-resolution source observations auditable but non-tradable.
-- Existing rows and columns remain backward-compatible.

ALTER TABLE earnings_fact_candidates
    DROP CONSTRAINT IF EXISTS
        earnings_fact_candidates_status_check;

ALTER TABLE earnings_fact_candidates
    ADD CONSTRAINT earnings_fact_candidates_status_check
    CHECK (
        status IN (
            'VALIDATED',
            'OBSERVED',
            'QUARANTINED',
            'EMITTED',
            'SUPERSEDED'
        )
    );

CREATE OR REPLACE VIEW earnings_source_race_observations AS
WITH ranked AS (
    SELECT
        fact.id AS fact_id,
        fact.scope_id,
        fact.ticker,
        fact.provider,
        telemetry.source_transport,
        coalesce(
            event.metadata ->> 'source_observation_mode',
            'active'
        ) AS observation_mode,
        fact.status AS fact_status,
        fact.value,
        event.filed_at AS provider_published_at,
        telemetry.transport_observed_at,
        telemetry.document_fetch_started_at,
        telemetry.document_fetch_completed_at,
        telemetry.document_fetch_route,
        telemetry.parse_completed_at,
        telemetry.fact_persisted_at,
        row_number() OVER (
            PARTITION BY fact.scope_id
            ORDER BY
                telemetry.transport_observed_at,
                fact.id
        ) AS source_race_rank,
        min(telemetry.transport_observed_at) OVER (
            PARTITION BY fact.scope_id
        ) AS winner_observed_at,
        first_value(fact.provider) OVER (
            PARTITION BY fact.scope_id
            ORDER BY
                telemetry.transport_observed_at,
                fact.id
        ) AS winner_provider,
        first_value(fact.value) OVER (
            PARTITION BY fact.scope_id
            ORDER BY
                telemetry.transport_observed_at,
                fact.id
        ) AS winner_value
    FROM earnings_fact_candidates AS fact
    JOIN earnings_source_events AS event
      ON event.id = fact.source_event_id
    JOIN earnings_source_processing_telemetry AS telemetry
      ON telemetry.source_event_id = event.id
    WHERE fact.status IN ('VALIDATED', 'OBSERVED', 'EMITTED')
)
SELECT
    fact_id,
    scope_id,
    ticker,
    provider,
    source_transport,
    observation_mode,
    fact_status,
    value,
    provider_published_at,
    transport_observed_at,
    document_fetch_started_at,
    document_fetch_completed_at,
    document_fetch_route,
    parse_completed_at,
    fact_persisted_at,
    source_race_rank,
    round(
        extract(
            epoch FROM (
                transport_observed_at - winner_observed_at
            )
        ) * 1000
    )::bigint AS source_race_lag_ms,
    winner_provider,
    winner_value,
    value = winner_value AS agrees_with_winner
FROM ranked;
