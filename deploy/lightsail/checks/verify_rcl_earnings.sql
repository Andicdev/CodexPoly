-- Fail closed without printing rule, profile, catalog, or claim contents.

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'rcl-2026q2-nongaap-eps-3pt97'
          AND scope_id = 'earnings:RCL:2026Q2'
          AND ticker = 'RCL'
          AND cik = '884887'
          AND fiscal_year = 2026
          AND fiscal_quarter = 2
          AND period_end = DATE '2026-06-30'
          AND estimated_release_at
              = TIMESTAMPTZ '2026-07-28 10:30:00+00'
          AND metric_kind = 'non_gaap_eps'
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND comparison_op = '>'
          AND strike = 3.97
          AND rounding_places = 2
          AND condition_id = '0x8701e9a10812190db05c6f703b4dd3d8d978ac171874c78bb26b2f23d7a38976'
          AND status = 'SHADOW'
          AND source_policy ->> 'metric_selection'
              = 'primary_headline_non_gaap_diluted_eps'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'company_ir' ->> 'kind'
              = 'html_listing'
          AND (
              source_policy -> 'company_ir'
                  ->> 'listing_utc_offset_minutes'
          )::integer = -240
          AND source_policy -> 'press_wire' ->> 'provider'
              = 'prnewswire'
          AND source_policy -> 'press_wire' ->> 'kind' = 'rss'
    ) <> 1 THEN
        RAISE EXCEPTION 'RCL earnings rule mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-rcl-2026q2'
          AND scope_id = 'earnings:RCL:2026Q2'
          AND source_name = 'earnings_resolution'
          AND account_name = 'abccbaq'
          AND condition_id = '0x8701e9a10812190db05c6f703b4dd3d8d978ac171874c78bb26b2f23d7a38976'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 50
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND prepare_from = TIMESTAMPTZ '2026-07-28 09:00:00+00'
          AND expires_at = TIMESTAMPTZ '2026-07-28 17:00:00+00'
          AND status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'RCL execution profile mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'RCL:2026-07-28'
          AND metric_options ->> 'market_basis' = 'non_gaap_eps'
          AND metric_options ->> 'comparison_op' = '>'
          AND metric_options ->> 'strike' = '3.97'
          AND jsonb_array_length(source_options) = 3
    ) <> 1 THEN
        RAISE EXCEPTION 'RCL earnings catalog mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:RCL:2026Q2'
    ) THEN
        RAISE EXCEPTION 'RCL execution claim must not exist';
    END IF;
END
$verification$;
