-- Fail closed without returning account, market, order, or secret data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'msft-2026q4-gaap-eps-4pt21'
          AND scope_id = 'earnings:MSFT:2026Q4'
          AND ticker = 'MSFT'
          AND cik = '789019'
          AND metric_kind = 'gaap_eps'
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND comparison_op = '>'
          AND strike = 4.21
          AND rounding_places = 2
          AND currency = 'USD'
          AND source_policy -> 'sec' ->> 'form_type' = '8-K'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'sec' ->> 'document_type' = 'EX-99.1'
          AND source_policy -> 'company_ir' ->> 'feed_url' =
              'https://news.microsoft.com/source/tag/investor-relations/feed/'
          AND source_policy -> 'company_ir' ->> 'provider' = 'company_ir'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'MSFT rule set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-msft-2026q4'
          AND scope_id = 'earnings:MSFT:2026Q4'
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
        RAISE EXCEPTION 'MSFT profile set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-msft-2026q4'
          AND profile_key = 'earnings-msft-2026q4'
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
              '2026-07-29-msft-post-market'
          AND metadata ->> 'armed_for_live' = 'false'
    ) <> 1 THEN
        RAISE EXCEPTION 'MSFT AUTO_PREFLIGHT schedule mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'MSFT:2026-07-29'
          AND ticker = 'MSFT'
          AND release_date = DATE '2026-07-29'
          AND market_session = 'POST_MARKET'
          AND schedule_status = 'CONFIRMED'
          AND integration_status = 'PARSER_ONLY'
    ) <> 1 THEN
        RAISE EXCEPTION 'MSFT catalog mismatch';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-msft-2026q4';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'MSFT notional is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:MSFT:2026Q4'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:MSFT:2026Q4'
    ) THEN
        RAISE EXCEPTION 'MSFT facts or claims already exist';
    END IF;
END
$verification$;

ROLLBACK;
