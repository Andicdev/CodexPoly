BEGIN TRANSACTION READ ONLY;

SELECT format(
    'template=%s:yes=%s:no=%s:quantity=%s:lifecycle=%s',
    template_key,
    yes_desired_price,
    no_desired_price,
    quantity,
    lifecycle_kind
)
FROM resolution_profile_templates
WHERE template_key = 'default';

SELECT format(
    'profile=%s:mode=%s:state=%s:status=%s:rule=%s:'
        || 'quantity=%s:price=%s/%s:preflight=%s:activate=%s:'
        || 'ready_until=%s:facts=%s:claims=%s',
    profile.profile_key,
    schedule.automation_mode,
    schedule.state,
    profile.status,
    rule.status,
    profile.quantity,
    profile.yes_desired_price,
    profile.no_desired_price,
    schedule.preflight_at,
    schedule.activate_at,
    coalesce(schedule.readiness_valid_until::text, 'none'),
    (
        SELECT count(*)
        FROM earnings_fact_candidates AS fact
        WHERE fact.scope_id = profile.scope_id
          AND fact.status = 'VALIDATED'
    ),
    (
        SELECT count(*)
        FROM resolution_execution_claims AS claim
        WHERE claim.scope_id = profile.scope_id
    )
)
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
JOIN earnings_market_rules AS rule
  ON rule.scope_id = profile.scope_id
WHERE schedule.metadata ->> 'block_id' =
    '2026-07-28-post-market'
ORDER BY profile.profile_key;

SELECT format(
    'block_profiles=%s:max_selected_notional=%s',
    count(*),
    sum(
        profile.quantity * greatest(
            profile.yes_desired_price,
            profile.no_desired_price
        )
    )
)
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
WHERE schedule.metadata ->> 'block_id' =
    '2026-07-28-post-market';

SELECT format(
    'heartbeat=%s:supervision=%s:trading=%s:age_seconds=%s',
    mode,
    supervision_enabled,
    trading_enabled,
    round(extract(epoch FROM now() - last_seen_at)::numeric, 3)
)
FROM resolution_runtime_heartbeats
WHERE runtime_key = 'hosted-resolution';

ROLLBACK;
