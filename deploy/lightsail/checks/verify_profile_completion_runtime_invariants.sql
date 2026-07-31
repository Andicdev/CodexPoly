-- Verify successful terminal lifecycle invariants without returning profile,
-- event, source, account, claim, or order data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.state = 'COMPLETED'
          AND (
              profile.status <> 'DISABLED'
              OR schedule.last_error_code IS NOT NULL
          )
    ) THEN
        RAISE EXCEPTION
            'COMPLETED schedule/profile invariant failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.state = 'COMPLETED'
          AND NOT EXISTS (
              SELECT 1
              FROM resolution_profile_schedule_events AS event
              WHERE event.schedule_id = schedule.id
                AND event.next_state = 'COMPLETED'
                AND (
                    (
                        event.event_kind =
                            'RESOLUTION_EXECUTION_COMPLETED'
                        AND event.previous_state = 'ACTIVE'
                        AND event.reason_code =
                            'resolution_execution_completed'
                    )
                    OR (
                        event.event_kind =
                            'RESOLUTION_EXECUTION_COMPLETED'
                        AND event.previous_state IN (
                            'ACTIVE',
                            'BLOCKED'
                        )
                        AND event.reason_code =
                            'historical_executed_claim_reconciled'
                        AND event.metadata
                            ->> 'historical_reconciliation' = 'true'
                        AND event.metadata
                            ->> 'existing_orders_left_unchanged' = 'true'
                    )
                    OR (
                        event.previous_state IN (
                            'PENDING',
                            'PREFLIGHTING',
                            'READY',
                            'ACTIVE',
                            'BLOCKED'
                        )
                        AND event.event_kind =
                            'POST_EVENT_RECONCILIATION_COMPLETED'
                        AND event.reason_code IN (
                            'official_result_observed_execution_missing',
                            'official_result_parser_quarantined'
                        )
                        AND schedule.metadata
                            ->> 'completion_reason' =
                            event.reason_code
                        AND event.metadata
                            ->> 'investigation_required' = 'true'
                        AND event.metadata
                            ->> 'live_execution_claim_present' = 'false'
                        AND event.metadata
                            ->> 'order_group_present' = 'false'
                        AND event.metadata
                            ->> 'existing_orders_left_unchanged' = 'true'
                        AND NOT EXISTS (
                            SELECT 1
                            FROM resolution_execution_claims AS claim
                            WHERE claim.scope_id = profile.scope_id
                        )
                        AND NOT EXISTS (
                            SELECT 1
                            FROM resolution_order_groups AS order_group
                            WHERE order_group.condition_id =
                                profile.condition_id
                        )
                        AND (
                            (
                                event.reason_code =
                                    'official_result_observed_execution_missing'
                                AND event.metadata
                                    ->> 'validated_fact_present' =
                                    'true'
                                AND EXISTS (
                                    SELECT 1
                                    FROM earnings_fact_candidates AS fact
                                    WHERE fact.scope_id =
                                        profile.scope_id
                                      AND fact.status IN (
                                          'VALIDATED',
                                          'EMITTED'
                                      )
                                )
                            )
                            OR (
                                event.reason_code =
                                    'official_result_parser_quarantined'
                                AND event.metadata
                                    ->> 'validated_fact_present' =
                                    'false'
                                AND NOT EXISTS (
                                    SELECT 1
                                    FROM earnings_fact_candidates AS fact
                                    WHERE fact.scope_id =
                                        profile.scope_id
                                      AND fact.status IN (
                                          'VALIDATED',
                                          'EMITTED'
                                      )
                                )
                                AND EXISTS (
                                    SELECT 1
                                    FROM earnings_source_events AS source
                                    WHERE source.scope_id =
                                        profile.scope_id
                                      AND source.status =
                                          'QUARANTINED'
                                )
                            )
                        )
                    )
                )
          )
    ) THEN
        RAISE EXCEPTION
            'COMPLETED schedule audit event is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedule_events AS event
        JOIN resolution_profile_schedules AS schedule
          ON schedule.id = event.schedule_id
        WHERE event.next_state = 'COMPLETED'
          AND schedule.state <> 'COMPLETED'
    ) THEN
        RAISE EXCEPTION
            'COMPLETED lifecycle state was overwritten';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedule_events
        WHERE event_kind IN (
            'RESOLUTION_EXECUTION_COMPLETED',
            'POST_EVENT_RECONCILIATION_COMPLETED'
        )
        GROUP BY schedule_id
        HAVING count(*) <> 1
    ) THEN
        RAISE EXCEPTION
            'COMPLETED lifecycle event is not idempotent';
    END IF;
END
$verification$;

ROLLBACK;
