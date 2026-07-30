-- One-shot, fail-closed retry for the reviewed RBLX filing after deploying
-- parser version 2. The update only makes the existing source event
-- retryable; the normal source -> signal -> execution path remains in charge.

BEGIN;

DO $retry$
DECLARE
    changed_rows integer;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-31 02:00:00+00' THEN
        RAISE EXCEPTION 'RBLX reviewed live window has closed';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_execution_profiles AS profile
        JOIN resolution_profile_schedules AS schedule
          ON schedule.profile_key = profile.profile_key
        WHERE profile.profile_key = 'earnings-rblx-2026q2'
          AND profile.scope_id = 'earnings:RBLX:2026Q2'
          AND profile.status = 'ENABLED'
          AND schedule.schedule_key =
              'schedule:earnings-rblx-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'ACTIVE'
          AND schedule.deactivate_at >
              TIMESTAMPTZ '2026-07-30 21:00:00+00'
    ) THEN
        RAISE EXCEPTION 'RBLX live profile is not active';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:RBLX:2026Q2'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:RBLX:2026Q2'
    ) THEN
        RAISE EXCEPTION 'RBLX already contains a fact or execution claim';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_source_events
        WHERE scope_id = 'earnings:RBLX:2026Q2'
          AND provider = 'sec'
          AND provider_event_id = '0001628280-26-051059'
          AND source_url =
              'https://www.sec.gov/Archives/edgar/data/1315098/000162828026051059/ex991-robloxq22026earnin.htm'
          AND status = 'NO_MATCH'
          AND error = 'roblox_gaap_diluted_eps_row_not_found'
    ) <> 1 THEN
        RAISE EXCEPTION 'reviewed RBLX source event precondition failed';
    END IF;

    UPDATE earnings_source_events
    SET
        status = 'ERROR',
        error = 'parser_retry_after_unicode_normalization_v2',
        updated_at = now()
    WHERE scope_id = 'earnings:RBLX:2026Q2'
      AND provider = 'sec'
      AND provider_event_id = '0001628280-26-051059'
      AND source_url =
          'https://www.sec.gov/Archives/edgar/data/1315098/000162828026051059/ex991-robloxq22026earnin.htm'
      AND status = 'NO_MATCH'
      AND error = 'roblox_gaap_diluted_eps_row_not_found';

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION 'RBLX retry did not update exactly one event';
    END IF;
END
$retry$;

COMMIT;
