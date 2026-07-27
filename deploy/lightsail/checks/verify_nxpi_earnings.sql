-- Fail closed without printing rule, profile, or catalog contents.

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'nxpi-2026q2-nongaap-eps-3pt53'
          AND scope_id = 'earnings:NXPI:2026Q2'
          AND ticker = 'NXPI'
          AND cik = '1413447'
          AND metric_kind = 'non_gaap_eps'
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND comparison_op = '>'
          AND strike = 3.53
          AND rounding_places = 2
          AND condition_id = '0x70676300a6fffc684d86850f30c8c34a64557f86c1f3fb377568bacb73585ff4'
          AND status = 'SHADOW'
          AND source_policy ->> 'metric_selection'
              = 'primary_headline_non_gaap_diluted_eps'
          AND source_policy -> 'company_ir' ->> 'kind' = 'rss'
          AND source_policy -> 'press_wire' ->> 'provider'
              = 'globenewswire'
    ) <> 1 THEN
        RAISE EXCEPTION 'NXPI earnings rule mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-nxpi-2026q2'
          AND scope_id = 'earnings:NXPI:2026Q2'
          AND account_name = 'abccbaq'
          AND condition_id = '0x70676300a6fffc684d86850f30c8c34a64557f86c1f3fb377568bacb73585ff4'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 50
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'NXPI execution profile mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'NXPI:2026-07-28'
          AND metric_options ->> 'market_basis' = 'non_gaap_eps'
          AND metric_options ->> 'comparison_op' = '>'
          AND metric_options ->> 'strike' = '3.53'
    ) <> 1 THEN
        RAISE EXCEPTION 'NXPI earnings catalog mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:NXPI:2026Q2'
    ) THEN
        RAISE EXCEPTION 'NXPI execution claim must not exist';
    END IF;
END
$verification$;
