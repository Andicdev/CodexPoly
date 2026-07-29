-- Fail closed without returning account, market, order, or secret data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'hood-2026q2-gaap-eps-0pt43'
          AND scope_id = 'earnings:HOOD:2026Q2'
          AND ticker = 'HOOD'
          AND cik = '1783879'
          AND fiscal_year = 2026
          AND fiscal_quarter = 2
          AND metric_kind = 'gaap_eps'
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND comparison_op = '>'
          AND strike = 0.43
          AND rounding_places = 2
          AND currency = 'USD'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'company_ir' ->> 'feed_url' =
              'https://investors.robinhood.com/rss/news-releases.xml'
          AND source_policy -> 'press_wire' ->> 'provider' =
              'globenewswire'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'HOOD rule set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-hood-2026q2'
          AND scope_id = 'earnings:HOOD:2026Q2'
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
        RAISE EXCEPTION 'HOOD profile set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-hood-2026q2'
          AND profile_key = 'earnings-hood-2026q2'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at =
              TIMESTAMPTZ '2026-07-29 17:45:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND deactivate_at =
              TIMESTAMPTZ '2026-07-30 02:00:00+00'
          AND metadata ->> 'block_id' =
              '2026-07-29-hood-post-market'
          AND metadata ->> 'armed_for_live' = 'false'
    ) <> 1 THEN
        RAISE EXCEPTION 'HOOD AUTO_PREFLIGHT schedule mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'HOOD:2026-07-29'
          AND ticker = 'HOOD'
          AND schedule_status = 'CONFIRMED'
          AND integration_status = 'PARSER_ONLY'
          AND conference_call_at =
              TIMESTAMPTZ '2026-07-29 21:00:00+00'
    ) <> 1 THEN
        RAISE EXCEPTION 'HOOD catalog mismatch';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-hood-2026q2';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'HOOD notional is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:HOOD:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:HOOD:2026Q2'
    ) THEN
        RAISE EXCEPTION 'HOOD facts or claims already exist';
    END IF;
END
$verification$;

ROLLBACK;
