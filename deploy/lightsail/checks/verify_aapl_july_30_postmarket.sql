-- Read-only verification for the disabled AAPL July 30 POST_MARKET profile.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'aapl-2026q3-gaap-eps-1pt89'
          AND scope_id = 'earnings:AAPL:2026Q3'
          AND ticker = 'AAPL'
          AND cik = '320193'
          AND metric_kind = 'gaap_eps'
          AND primary_basis = 'diluted'
          AND comparison_op = '>'
          AND strike = 1.89
          AND source_policy -> 'company_ir' ->> 'provider' =
              'company_ir'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'AAPL rule is not prepared';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-aapl-2026q3'
          AND scope_id = 'earnings:AAPL:2026Q3'
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
        RAISE EXCEPTION 'AAPL disabled profile is not prepared';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-aapl-2026q3'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state IN ('PENDING', 'PREFLIGHTING', 'READY')
          AND preflight_at =
              TIMESTAMPTZ '2026-07-30 18:15:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-30 18:30:00+00'
          AND earliest_signal_at =
              TIMESTAMPTZ '2026-07-30 20:30:00+00'
          AND activation_safety_lead_seconds = 7200
          AND timing_contract_version = 1
          AND activate_at <= earliest_signal_at
              - activation_safety_lead_seconds * interval '1 second'
    ) <> 1 THEN
        RAISE EXCEPTION 'AAPL schedule is not safely prepared';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:AAPL:2026Q3'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:AAPL:2026Q3'
    ) THEN
        RAISE EXCEPTION 'AAPL scope already contains trading state';
    END IF;
END
$verify$;

ROLLBACK;
