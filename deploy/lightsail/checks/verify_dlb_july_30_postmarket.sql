-- Read-only verification for the disabled DLB July 30 profile.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'dlb-2026q3-nongaap-eps-0pt67'
          AND scope_id = 'earnings:DLB:2026Q3'
          AND ticker = 'DLB'
          AND cik = '1308547'
          AND metric_kind = 'non_gaap_eps'
          AND primary_basis = 'diluted'
          AND comparison_op = '>'
          AND strike = 0.67
          AND source_policy -> 'company_ir' ->> 'provider' =
              'company_ir'
          AND source_policy -> 'press_wire' ->> 'provider' =
              'prnewswire'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'DLB rule is not prepared';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-dlb-2026q3'
          AND scope_id = 'earnings:DLB:2026Q3'
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
        RAISE EXCEPTION 'DLB disabled profile is not prepared';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-dlb-2026q3'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state IN ('PENDING', 'PREFLIGHTING', 'READY')
          AND preflight_at =
              TIMESTAMPTZ '2026-07-30 18:00:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-30 18:15:00+00'
          AND earliest_signal_at =
              TIMESTAMPTZ '2026-07-30 20:15:00+00'
          AND activation_safety_lead_seconds = 7200
          AND timing_contract_version = 1
          AND activate_at <= earliest_signal_at
              - activation_safety_lead_seconds * interval '1 second'
    ) <> 1 THEN
        RAISE EXCEPTION 'DLB schedule is not safely prepared';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:DLB:2026Q3'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:DLB:2026Q3'
    ) THEN
        RAISE EXCEPTION 'DLB scope already contains trading state';
    END IF;
END
$verify$;

ROLLBACK;
