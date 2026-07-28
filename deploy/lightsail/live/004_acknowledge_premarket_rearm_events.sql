BEGIN;

DO $guard$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE event_key IN (
            'manual-rearm:earnings-rcl-2026q2:2026-07-28-pre-market-r1',
            'manual-rearm:earnings-ba-2026q2:2026-07-28-pre-market-r1',
            'manual-rearm:earnings-jblu-2026q2:2026-07-28-pre-market-r1',
            'manual-rearm:earnings-spgi-2026q2:2026-07-28-pre-market-r1'
        )
          AND previous_state = 'BLOCKED'
          AND next_state = 'PENDING'
          AND event_kind = 'PROFILE_REARMED'
          AND notification_enqueued_at IS NULL
    ) <> 4 THEN
        RAISE EXCEPTION 'pre-market rearm event acknowledgement guard failed';
    END IF;
END
$guard$;

UPDATE resolution_profile_schedule_events
SET notification_enqueued_at = now()
WHERE event_key IN (
    'manual-rearm:earnings-rcl-2026q2:2026-07-28-pre-market-r1',
    'manual-rearm:earnings-ba-2026q2:2026-07-28-pre-market-r1',
    'manual-rearm:earnings-jblu-2026q2:2026-07-28-pre-market-r1',
    'manual-rearm:earnings-spgi-2026q2:2026-07-28-pre-market-r1'
)
  AND notification_enqueued_at IS NULL;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE event_key IN (
            'manual-rearm:earnings-rcl-2026q2:2026-07-28-pre-market-r1',
            'manual-rearm:earnings-ba-2026q2:2026-07-28-pre-market-r1',
            'manual-rearm:earnings-jblu-2026q2:2026-07-28-pre-market-r1',
            'manual-rearm:earnings-spgi-2026q2:2026-07-28-pre-market-r1'
        )
          AND notification_enqueued_at IS NOT NULL
    ) <> 4 THEN
        RAISE EXCEPTION 'pre-market rearm event acknowledgement failed';
    END IF;
END
$verify$;

COMMIT;
