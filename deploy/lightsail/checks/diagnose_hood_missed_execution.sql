-- Read-only binary diagnostic for the July 29 HOOD missed execution.
-- It proves that the official fact was eligible, no execution path started,
-- and the final pre-event lifecycle transition was a preflight block.

BEGIN TRANSACTION READ ONLY;

DO $diagnostic$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_fact_candidates AS fact
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = fact.scope_id
        WHERE rule.rule_key = 'hood-2026q2-gaap-eps-0pt43'
          AND rule.status IN ('SHADOW', 'WATCHING')
          AND fact.scope_id = 'earnings:HOOD:2026Q2'
          AND fact.ticker = rule.ticker
          AND fact.cik = rule.cik
          AND fact.period_end = rule.period_end
          AND fact.metric_kind = rule.metric_kind
          AND fact.currency = rule.currency
          AND fact.provider = 'sec'
          AND fact.value = 0.62
          AND fact.status = 'VALIDATED'
          AND fact.authority = 'official_company'
          AND fact.confidence = 1
          AND (
              fact.basis = rule.primary_basis
              OR (
                  rule.primary_basis = 'diluted'
                  AND fact.basis = 'basic_and_diluted'
              )
          )
    ) <> 1 THEN
        RAISE EXCEPTION 'HOOD eligible validated fact is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:HOOD:2026Q2'
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) OR EXISTS (
        SELECT 1
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        WHERE profile.profile_key = 'earnings-hood-2026q2'
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
    ) THEN
        RAISE EXCEPTION 'HOOD live execution evidence unexpectedly exists';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE profile_key = 'earnings-hood-2026q2'
          AND next_state = 'BLOCKED'
          AND event_kind = 'PREFLIGHT_BLOCKED'
          AND reason_code = 'authenticated_preflight_not_ready'
          AND created_at < (
              SELECT created_at
              FROM resolution_profile_schedule_events
              WHERE event_key =
                    'postmarket-close:earnings-hood-2026q2:2026-07-29'
          )
          AND created_at = (
              SELECT max(prior.created_at)
              FROM resolution_profile_schedule_events AS prior
              WHERE prior.profile_key = 'earnings-hood-2026q2'
                AND prior.next_state = 'BLOCKED'
                AND prior.created_at < (
                    SELECT created_at
                    FROM resolution_profile_schedule_events
                    WHERE event_key =
                          'postmarket-close:earnings-hood-2026q2:2026-07-29'
                )
          )
    ) <> 1 THEN
        RAISE EXCEPTION 'HOOD final pre-event block was not preflight';
    END IF;
END
$diagnostic$;

ROLLBACK;
