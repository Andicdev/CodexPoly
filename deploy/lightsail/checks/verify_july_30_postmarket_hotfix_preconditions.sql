-- Fail-closed, read-only guard for the July 30 SEC promotion and RBLX parser
-- hotfix. A successful run confirms that only the three missed live scopes
-- remain eligible for recovery.

BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    target_scope text;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM resolution_runtime_heartbeats
        WHERE runtime_key = 'hosted-resolution'
          AND mode = 'live'
          AND supervision_enabled
          AND trading_enabled
          AND last_seen_at >= now() - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION 'live resolution heartbeat is missing or stale';
    END IF;

    FOREACH target_scope IN ARRAY ARRAY[
        'earnings:RIVN:2026Q2',
        'earnings:RDDT:2026Q2',
        'earnings:RBLX:2026Q2'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM resolution_execution_profiles AS profile
            JOIN resolution_profile_schedules AS schedule
              ON schedule.profile_key = profile.profile_key
            JOIN earnings_market_rules AS rule
              ON rule.scope_id = profile.scope_id
            WHERE profile.scope_id = target_scope
              AND profile.status = 'ENABLED'
              AND schedule.automation_mode = 'AUTO_LIVE'
              AND schedule.state = 'ACTIVE'
              AND schedule.deactivate_at > now()
              AND rule.status = 'SHADOW'
        ) THEN
            RAISE EXCEPTION
                'target scope is not an active reviewed live profile: %',
                target_scope;
        END IF;

        IF EXISTS (
            SELECT 1
            FROM earnings_fact_candidates
            WHERE scope_id = target_scope
              AND status IN ('VALIDATED', 'EMITTED')
        ) OR EXISTS (
            SELECT 1
            FROM resolution_execution_claims
            WHERE scope_id = target_scope
        ) THEN
            RAISE EXCEPTION
                'target scope already contains a validated fact or claim: %',
                target_scope;
        END IF;
    END LOOP;

    IF (
        SELECT count(*)
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:RIVN:2026Q2'
          AND status = 'OBSERVED'
    ) <> 1 OR NOT EXISTS (
        SELECT 1
        FROM earnings_source_events AS event
        JOIN earnings_fact_candidates AS fact
          ON fact.source_event_id = event.id
        WHERE event.scope_id = 'earnings:RIVN:2026Q2'
          AND event.status = 'PARSED'
          AND fact.status = 'OBSERVED'
    ) THEN
        RAISE EXCEPTION 'RIVN observed-fact promotion precondition failed';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:RDDT:2026Q2'
          AND status = 'OBSERVED'
    ) <> 1 OR NOT EXISTS (
        SELECT 1
        FROM earnings_source_events AS event
        JOIN earnings_fact_candidates AS fact
          ON fact.source_event_id = event.id
        WHERE event.scope_id = 'earnings:RDDT:2026Q2'
          AND event.status = 'PARSED'
          AND fact.status = 'OBSERVED'
    ) THEN
        RAISE EXCEPTION 'RDDT observed-fact promotion precondition failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:RBLX:2026Q2'
    ) OR NOT EXISTS (
        SELECT 1
        FROM earnings_source_events
        WHERE scope_id = 'earnings:RBLX:2026Q2'
          AND status = 'NO_MATCH'
          AND error = 'roblox_gaap_diluted_eps_row_not_found'
    ) THEN
        RAISE EXCEPTION 'RBLX parser-retry precondition failed';
    END IF;

END
$verify$;

ROLLBACK;
