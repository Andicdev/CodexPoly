-- Read-only verification for the disabled AMZN July 30 POST_MARKET profile.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'amzn-2026q2-gaap-eps-1pt82'
          AND scope_id = 'earnings:AMZN:2026Q2'
          AND ticker = 'AMZN'
          AND cik = '1018724'
          AND metric_kind = 'gaap_eps'
          AND primary_basis = 'diluted'
          AND comparison_op = '>'
          AND strike = 1.82
          AND condition_id =
              '0x778f7b1584c2d2585944ac4020dcb187ac86f4552293ad7dd9bb1c79e458e4fb'
          AND source_policy -> 'company_ir' ->> 'provider' =
              'company_ir'
          AND source_policy -> 'press_wire' ->> 'provider' =
              'businesswire'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'AMZN rule is not prepared';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-amzn-2026q2'
          AND scope_id = 'earnings:AMZN:2026Q2'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'AMZN disabled profile is not prepared';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'AMZN:2026-07-30'
          AND schedule_status = 'CONFIRMED'
          AND market_session = 'POST_MARKET'
          AND earliest_expected_release_at =
              TIMESTAMPTZ '2026-07-30 20:00:00+00'
          AND conference_call_at =
              TIMESTAMPTZ '2026-07-30 21:00:00+00'
          AND timing_basis = 'HISTORICAL_PATTERN'
          AND activation_safety_lead_seconds = 7200
    ) <> 1 THEN
        RAISE EXCEPTION 'AMZN release timing is not prepared';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-amzn-2026q2'
          AND profile_key = 'earnings-amzn-2026q2'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state IN ('PENDING', 'PREFLIGHTING', 'READY')
          AND activate_at =
              TIMESTAMPTZ '2026-07-30 18:00:00+00'
          AND earliest_signal_at =
              TIMESTAMPTZ '2026-07-30 20:00:00+00'
          AND activation_safety_lead_seconds = 7200
          AND timing_contract_version = 1
          AND activate_at <= earliest_signal_at
              - activation_safety_lead_seconds * interval '1 second'
    ) <> 1 THEN
        RAISE EXCEPTION 'AMZN schedule is not safely prepared';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:AMZN:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:AMZN:2026Q2'
    ) THEN
        RAISE EXCEPTION 'AMZN scope already contains trading state';
    END IF;
END
$verify$;

ROLLBACK;
