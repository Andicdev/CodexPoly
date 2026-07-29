-- Read-only source-to-exchange timing audit for the July 29 PRE_MARKET block.
-- The SEC rows predate the acceptanceDateTime timezone fix in image cb5e5a.
-- For those historical rows, reinterpret the stored UTC clock fields as
-- America/New_York wall time before calculating normalized source latency.

BEGIN TRANSACTION READ ONLY;

SELECT format(
    'ticker=%s,provider=%s,status=%s,published=%s,received=%s,normalized_source_ms=%s,parsed=%s,parse_ms=%s,value=%s,error=%s',
    event.ticker,
    event.provider,
    event.status,
    CASE
        WHEN event.provider = 'sec' THEN
            (event.filed_at AT TIME ZONE 'UTC')
                AT TIME ZONE 'America/New_York'
        ELSE event.filed_at
    END,
    event.received_at,
    round(
        extract(
            epoch FROM event.received_at
                - CASE
                    WHEN event.provider = 'sec' THEN
                        (event.filed_at AT TIME ZONE 'UTC')
                            AT TIME ZONE 'America/New_York'
                    ELSE event.filed_at
                END
        ) * 1000
    ),
    fact.detected_at,
    CASE
        WHEN fact.detected_at IS NULL THEN NULL
        ELSE round(
            extract(
                epoch FROM fact.detected_at - event.received_at
            ) * 1000
        )
    END,
    fact.value,
    coalesce(event.error, 'none')
)
FROM earnings_source_events AS event
LEFT JOIN earnings_fact_candidates AS fact
  ON fact.source_event_id = event.id
WHERE event.scope_id IN (
    'earnings:SOFI:2026Q2',
    'earnings:PG:2026Q4',
    'earnings:HUM:2026Q2',
    'earnings:WING:2026Q2',
    'earnings:ARCC:2026Q2',
    'earnings:IART:2026Q2',
    'earnings:GRMN:2026Q2',
    'earnings:CBRE:2026Q2',
    'earnings:PAG:2026Q2'
)
ORDER BY event.ticker, event.received_at, event.id;

SELECT format(
    'ticker=%s,fact_provider=%s,fact_detected=%s,claim_created=%s,claim_completed=%s,decision_ms=%s,exchange_ms=%s,total_hot_path_ms=%s,outcome=%s,effective_price=%s,status=%s',
    profile.metadata ->> 'ticker',
    fact.provider,
    fact.detected_at,
    claim.created_at,
    claim.completed_at,
    CASE
        WHEN claim.created_at IS NULL THEN NULL
        ELSE round(
            extract(
                epoch FROM claim.created_at - fact.detected_at
            ) * 1000
        )
    END,
    CASE
        WHEN claim.completed_at IS NULL THEN NULL
        ELSE round(
            extract(
                epoch FROM claim.completed_at - claim.created_at
            ) * 1000
        )
    END,
    CASE
        WHEN claim.completed_at IS NULL THEN NULL
        ELSE round(
            extract(
                epoch FROM claim.completed_at - fact.detected_at
            ) * 1000
        )
    END,
    claim.outcome,
    claim.effective_price,
    claim.status
)
FROM resolution_execution_profiles AS profile
JOIN LATERAL (
    SELECT candidate.*
    FROM earnings_fact_candidates AS candidate
    WHERE candidate.scope_id = profile.scope_id
      AND candidate.status IN ('VALIDATED', 'EMITTED')
    ORDER BY candidate.detected_at, candidate.id
    LIMIT 1
) AS fact ON true
LEFT JOIN LATERAL (
    SELECT candidate.*
    FROM resolution_execution_claims AS candidate
    WHERE candidate.scope_id = profile.scope_id
      AND candidate.status <> 'EXPIRED'
    ORDER BY candidate.created_at, candidate.id
    LIMIT 1
) AS claim ON true
WHERE profile.profile_key IN (
    'earnings-sofi-2026q2',
    'earnings-pg-2026q4',
    'earnings-hum-2026q2',
    'earnings-wing-2026q2',
    'earnings-arcc-2026q2',
    'earnings-iart-2026q2',
    'earnings-grmn-2026q2',
    'earnings-cbre-2026q2',
    'earnings-pag-2026q2'
)
ORDER BY profile.profile_key;

ROLLBACK;
