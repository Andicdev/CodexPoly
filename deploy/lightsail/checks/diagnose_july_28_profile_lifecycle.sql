BEGIN TRANSACTION READ ONLY;

SELECT format(
    'profile=%s,schedule=%s,mode=%s,state=%s,profile_status=%s,error=%s',
    profile.profile_key,
    schedule.schedule_key,
    schedule.automation_mode,
    schedule.state,
    profile.status,
    coalesce(schedule.last_error_code, 'none')
)
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
WHERE schedule.activate_at >= TIMESTAMPTZ '2026-07-28 00:00:00+00'
  AND schedule.activate_at < TIMESTAMPTZ '2026-07-29 00:00:00+00'
ORDER BY schedule.activate_at, profile.profile_key;

ROLLBACK;
