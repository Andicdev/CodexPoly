-- Read-only binary diagnostic for the July 29 EA schedule block.
-- EA was active before the operator decision, but no official event,
-- execution claim, or order group was observed.

BEGIN TRANSACTION READ ONLY;

DO $diagnostic$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE event_key =
              'schedule-block:earnings-ea-2027q1:2026-07-29'
          AND previous_state = 'ACTIVE'
          AND next_state = 'BLOCKED'
          AND reason_code = 'official_schedule_unconfirmed'
    ) <> 1 THEN
        RAISE EXCEPTION 'EA official schedule block lifecycle is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:EA:2027Q1'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:EA:2027Q1'
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) OR EXISTS (
        SELECT 1
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        WHERE profile.profile_key = 'earnings-ea-2027q1'
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
    ) THEN
        RAISE EXCEPTION 'EA live event evidence unexpectedly exists';
    END IF;
END
$diagnostic$;

ROLLBACK;
