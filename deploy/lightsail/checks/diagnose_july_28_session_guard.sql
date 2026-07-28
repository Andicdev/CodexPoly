BEGIN TRANSACTION READ ONLY;

SELECT format(
    'profile=%s:mode=%s:state=%s:profile_status=%s:rule_status=%s:deactivate=%s',
    schedule.profile_key,
    schedule.automation_mode,
    schedule.state,
    profile.status,
    rule.status,
    schedule.deactivate_at
)
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
JOIN earnings_market_rules AS rule
  ON rule.scope_id = profile.scope_id
WHERE schedule.profile_key IN (
    'earnings-pypl-2026q2',
    'earnings-ups-2026q2',
    'earnings-hlt-2026q2',
    'earnings-ivz-2026q2',
    'earnings-ko-2026q2',
    'earnings-rcl-2026q2',
    'earnings-ba-2026q2',
    'earnings-jblu-2026q2',
    'earnings-spgi-2026q2',
    'earnings-csgp-2026q2',
    'earnings-czr-2026q2',
    'earnings-f-2026q2',
    'earnings-nxpi-2026q2',
    'earnings-v-2026q3'
)
ORDER BY schedule.activate_at, schedule.profile_key;

SELECT format(
    'fact=%s:%s:%s',
    ticker,
    status,
    count(*)
)
FROM earnings_fact_candidates
WHERE scope_id IN (
    'earnings:RCL:2026Q2',
    'earnings:BA:2026Q2',
    'earnings:JBLU:2026Q2',
    'earnings:SPGI:2026Q2',
    'earnings:UPS:2026Q2'
)
GROUP BY ticker, status
ORDER BY ticker, status;

SELECT format(
    'claim=%s:%s:%s',
    scope_id,
    status,
    count(*)
)
FROM resolution_execution_claims
WHERE scope_id IN (
    'earnings:RCL:2026Q2',
    'earnings:BA:2026Q2',
    'earnings:JBLU:2026Q2',
    'earnings:SPGI:2026Q2',
    'earnings:UPS:2026Q2'
)
GROUP BY scope_id, status
ORDER BY scope_id, status;

SELECT format(
    'catalog=UPS:%s',
    schedule_status
)
FROM earnings_release_catalog
WHERE event_key = 'UPS:2026-07-28';

SELECT format(
    'heartbeat=%s:%s:%s:age_seconds=%s',
    mode,
    supervision_enabled,
    trading_enabled,
    round(extract(epoch FROM now() - last_seen_at)::numeric, 3)
)
FROM resolution_runtime_heartbeats
WHERE runtime_key = 'hosted-resolution';

SELECT format(
    'unnotified=%s:%s:%s:%s',
    id,
    event_key,
    next_state,
    event_kind
)
FROM resolution_profile_schedule_events
WHERE notification_enqueued_at IS NULL
ORDER BY id
LIMIT 20;

ROLLBACK;
