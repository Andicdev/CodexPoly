-- Tighten only public-source title routing for the still-disarmed July 28
-- post-market profiles. No profile, schedule, fact, or claim is created.

BEGIN;

DO $guard$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key IN (
            'csgp-2026q2-gaap-eps-0pt10',
            'nxpi-2026q2-nongaap-eps-3pt53'
        )
          AND status = 'SHADOW'
    ) <> 2 THEN
        RAISE EXCEPTION 'postmarket public-source rules are not disarmed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'earnings-csgp-2026q2',
            'earnings-nxpi-2026q2'
        )
          AND status = 'DISABLED'
    ) <> 2 THEN
        RAISE EXCEPTION 'postmarket public-source profiles are not disabled';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_source_events
        WHERE scope_id IN (
            'earnings:CSGP:2026Q2',
            'earnings:NXPI:2026Q2'
        )
    ) OR EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id IN (
            'earnings:CSGP:2026Q2',
            'earnings:NXPI:2026Q2'
        )
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:CSGP:2026Q2',
            'earnings:NXPI:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'postmarket public-source scope is no longer clean';
    END IF;
END
$guard$;

UPDATE earnings_market_rules
SET
    source_policy = jsonb_set(
        source_policy,
        '{company_ir,title_all}',
        '["CoStar Group", "Q2"]'::jsonb,
        false
    ),
    updated_at = now()
WHERE rule_key = 'csgp-2026q2-gaap-eps-0pt10';

UPDATE earnings_market_rules
SET
    source_policy = jsonb_set(
        jsonb_set(
            source_policy,
            '{company_ir,title_none}',
            '["to report", "conference call"]'::jsonb,
            false
        ),
        '{press_wire,title_none}',
        '["to report", "conference call"]'::jsonb,
        false
    ),
    updated_at = now()
WHERE rule_key = 'nxpi-2026q2-nongaap-eps-3pt53';

DO $verify$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'csgp-2026q2-gaap-eps-0pt10'
          AND source_policy #> '{company_ir,title_all}'
              = '["CoStar Group", "Q2"]'::jsonb
    ) THEN
        RAISE EXCEPTION 'CSGP public-source guard was not installed';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'nxpi-2026q2-nongaap-eps-3pt53'
          AND source_policy #> '{company_ir,title_none}'
              = '["to report", "conference call"]'::jsonb
          AND source_policy #> '{press_wire,title_none}'
              = '["to report", "conference call"]'::jsonb
    ) THEN
        RAISE EXCEPTION 'NXPI public-source guards were not installed';
    END IF;
END
$verify$;

COMMIT;
