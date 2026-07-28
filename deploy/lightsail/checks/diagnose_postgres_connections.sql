BEGIN TRANSACTION READ ONLY;

SELECT format(
    'connections=%s,max=%s',
    count(*),
    current_setting('max_connections')
)
FROM pg_stat_activity;

SELECT format(
    'group=%s:%s:%s:%s',
    coalesce(usename, 'none'),
    coalesce(nullif(application_name, ''), 'none'),
    coalesce(state, 'none'),
    count(*)
)
FROM pg_stat_activity
GROUP BY usename, application_name, state
ORDER BY count(*) DESC, usename, application_name, state;

ROLLBACK;
