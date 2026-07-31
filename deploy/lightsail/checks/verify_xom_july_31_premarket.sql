-- Read-only verification for the disabled XOM July 31 PRE_MARKET profile.

BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*) FROM earnings_market_rules
        WHERE rule_key = 'xom-2026q2-nongaap-eps-3pt66'
          AND scope_id = 'earnings:XOM:2026Q2'
          AND ticker = 'XOM'
          AND cik = '2115436'
          AND metric_kind = 'non_gaap_eps'
          AND primary_basis = 'diluted'
          AND comparison_op = '>'
          AND strike = 3.66
          AND market_slug =
              'xom-quarterly-earnings-nongaap-eps-07-31-2026-3pt66'
          AND condition_id =
              '0x4f47cfcf38650017dfcbf87a05776eb9692bdfab37d8bd8bcdba8733c7eb0fcd'
          AND source_policy ->> 'predecessor_cik' = '34088'
          AND source_policy -> 'company_ir' ->> 'provider' = 'company_ir'
          AND source_policy -> 'press_wire' ->> 'provider' = 'businesswire'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'XOM rule invariant failed';
    END IF;

    IF (
        SELECT count(*) FROM earnings_release_catalog
        WHERE event_key = 'XOM:2026-07-31'
          AND market_session = 'PRE_MARKET'
          AND scheduled_release_at =
              TIMESTAMPTZ '2026-07-31 10:30:00+00'
          AND conference_call_at =
              TIMESTAMPTZ '2026-07-31 13:30:00+00'
          AND earliest_expected_release_at =
              TIMESTAMPTZ '2026-07-31 10:30:00+00'
          AND timing_basis = 'OFFICIAL_EXACT'
          AND activation_safety_lead_seconds = 7200
          AND integration_status = 'PARSER_ONLY'
    ) <> 1 THEN
        RAISE EXCEPTION 'XOM catalog invariant failed';
    END IF;

    IF (
        SELECT count(*) FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-xom-2026q2'
          AND scope_id = 'earnings:XOM:2026Q2'
          AND account_name = 'abccbaq'
          AND condition_id =
              '0x4f47cfcf38650017dfcbf87a05776eb9692bdfab37d8bd8bcdba8733c7eb0fcd'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'XOM profile invariant failed';
    END IF;

    IF (
        SELECT count(*) FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-xom-2026q2'
          AND profile_key = 'earnings-xom-2026q2'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at = TIMESTAMPTZ '2026-07-31 08:15:00+00'
          AND activate_at = TIMESTAMPTZ '2026-07-31 08:30:00+00'
          AND deactivate_at = TIMESTAMPTZ '2026-07-31 14:00:00+00'
          AND earliest_signal_at =
              TIMESTAMPTZ '2026-07-31 10:30:00+00'
          AND activation_safety_lead_seconds = 7200
          AND timing_basis = 'OFFICIAL_EXACT'
          AND timing_contract_version = 1
          AND activate_at <= earliest_signal_at
              - activation_safety_lead_seconds * interval '1 second'
          AND metadata ->> 'armed_for_live' = 'false'
    ) <> 1 THEN
        RAISE EXCEPTION 'XOM schedule invariant failed';
    END IF;

    IF EXISTS (
        SELECT 1 FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:XOM:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = 'earnings:XOM:2026Q2'
    ) OR EXISTS (
        SELECT 1 FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0x4f47cfcf38650017dfcbf87a05776eb9692bdfab37d8bd8bcdba8733c7eb0fcd'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'XOM scope is not clean';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-xom-2026q2';
    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'XOM reviewed notional is invalid';
    END IF;
END
$verify$;

ROLLBACK;
