BEGIN TRANSACTION READ ONLY;
DO $verify$
BEGIN
    IF (
        SELECT count(*) FROM earnings_market_rules
        WHERE rule_key = 'rddt-2026q2-gaap-eps-0pt97'
          AND scope_id = 'earnings:RDDT:2026Q2'
          AND ticker = 'RDDT'
          AND cik = '1713445'
          AND metric_kind = 'gaap_eps'
          AND primary_basis = 'diluted'
          AND strike = 0.97
          AND source_policy -> 'company_ir' ->> 'provider' = 'company_ir'
          AND source_policy -> 'press_wire' ->> 'provider' = 'businesswire'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'RDDT rule is not prepared';
    END IF;
    IF (
        SELECT count(*) FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-rddt-2026q2'
          AND scope_id = 'earnings:RDDT:2026Q2'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'RDDT disabled profile is not prepared';
    END IF;
    IF (
        SELECT count(*) FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-rddt-2026q2'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state IN ('PENDING', 'PREFLIGHTING', 'READY')
          AND preflight_at = TIMESTAMPTZ '2026-07-30 17:53:00+00'
          AND activate_at = TIMESTAMPTZ '2026-07-30 18:08:00+00'
          AND earliest_signal_at = TIMESTAMPTZ '2026-07-30 20:08:00+00'
          AND activation_safety_lead_seconds = 7200
    ) <> 1 THEN
        RAISE EXCEPTION 'RDDT schedule is not safely prepared';
    END IF;
    IF EXISTS (
        SELECT 1 FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:RDDT:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = 'earnings:RDDT:2026Q2'
    ) THEN
        RAISE EXCEPTION 'RDDT scope already contains trading state';
    END IF;
END
$verify$;
ROLLBACK;
