-- Fail closed without returning account, market, order, or secret data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'qcom-2026q3-nongaap-eps-2pt23'
          AND scope_id = 'earnings:QCOM:2026Q3'
          AND ticker = 'QCOM'
          AND cik = '804328'
          AND metric_kind = 'non_gaap_eps'
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND comparison_op = '>'
          AND strike = 2.23
          AND rounding_places = 2
          AND currency = 'USD'
          AND source_policy -> 'sec' ->> 'form_type' = '8-K'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'sec' ->> 'document_type' = 'EX-99.1'
          AND source_policy -> 'company_ir' ->> 'feed_url' =
              'https://s204.q4cdn.com/645488518/files/doc_financials/2026/q3/FY2026-3rd-Quarter-Earnings-Release.pdf'
          AND source_policy -> 'company_ir' ->> 'kind' =
              'direct_document'
          AND source_policy -> 'company_ir' ->> 'provider' =
              'company_ir'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'QCOM rule set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-qcom-2026q3'
          AND scope_id = 'earnings:QCOM:2026Q3'
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
        RAISE EXCEPTION 'QCOM profile set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-qcom-2026q3'
          AND profile_key = 'earnings-qcom-2026q3'
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
              '2026-07-29-qcom-post-market'
          AND metadata ->> 'armed_for_live' = 'false'
    ) <> 1 THEN
        RAISE EXCEPTION 'QCOM AUTO_PREFLIGHT schedule mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'QCOM:2026-07-29'
          AND ticker = 'QCOM'
          AND release_date = DATE '2026-07-29'
          AND market_session = 'POST_MARKET'
          AND schedule_status = 'CONFIRMED'
          AND integration_status = 'PARSER_ONLY'
    ) <> 1 THEN
        RAISE EXCEPTION 'QCOM catalog mismatch';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-qcom-2026q3';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'QCOM notional is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:QCOM:2026Q3'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:QCOM:2026Q3'
    ) THEN
        RAISE EXCEPTION 'QCOM facts or claims already exist';
    END IF;
END
$verification$;

ROLLBACK;
