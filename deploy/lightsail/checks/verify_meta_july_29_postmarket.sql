-- Fail closed without returning account, market, order, or secret data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'meta-2026q2-gaap-eps-7pt20'
          AND scope_id = 'earnings:META:2026Q2'
          AND ticker = 'META'
          AND cik = '1326801'
          AND metric_kind = 'gaap_eps'
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND comparison_op = '>'
          AND strike = 7.20
          AND rounding_places = 2
          AND currency = 'USD'
          AND source_policy -> 'sec' ->> 'form_type' = '8-K'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'sec' ->> 'document_type' = 'EX-99.1'
          AND source_policy -> 'company_ir' ->> 'feed_url' =
              'https://investor.atmeta.com/rss/pressrelease.aspx'
          AND source_policy -> 'company_ir' ->> 'provider' = 'company_ir'
          AND source_policy -> 'press_wire' ->> 'provider' = 'prnewswire'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'META rule set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-meta-2026q2'
          AND scope_id = 'earnings:META:2026Q2'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND prepare_from =
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND expires_at =
              TIMESTAMPTZ '2026-07-30 02:00:00+00'
          AND status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'META profile set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-meta-2026q2'
          AND profile_key = 'earnings-meta-2026q2'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at =
              TIMESTAMPTZ '2026-07-29 17:45:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND deactivate_at =
              TIMESTAMPTZ '2026-07-30 02:00:00+00'
          AND metadata ->> 'live_block' = 'POST_MARKET'
          AND metadata ->> 'block_id' =
              '2026-07-29-meta-post-market'
          AND metadata ->> 'armed_for_live' = 'false'
    ) <> 1 THEN
        RAISE EXCEPTION 'META AUTO_PREFLIGHT schedule mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'META:2026-07-29'
          AND ticker = 'META'
          AND release_date = DATE '2026-07-29'
          AND market_session = 'POST_MARKET'
          AND schedule_status = 'CONFIRMED'
          AND integration_status = 'PARSER_ONLY'
    ) <> 1 THEN
        RAISE EXCEPTION 'META catalog mismatch';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-meta-2026q2';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'META notional is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:META:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:META:2026Q2'
    ) THEN
        RAISE EXCEPTION 'META facts or claims already exist';
    END IF;
END
$verification$;

ROLLBACK;
