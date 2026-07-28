-- Fail closed without returning profile, market, account, or order data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key IN (
            'sofi-2026q2-gaap-eps-0pt11',
            'pg-2026q4-nongaap-eps-1pt41',
            'hum-2026q2-nongaap-eps-7pt00',
            'wing-2026q2-gaap-eps-1pt03',
            'arcc-2026q2-nongaap-eps-0pt47',
            'iart-2026q2-nongaap-eps-0pt48',
            'grmn-2026q2-nongaap-eps-2pt29',
            'cbre-2026q2-gaap-eps-1pt32',
            'pag-2026q2-gaap-eps-3pt39'
        )
          AND status = 'SHADOW'
          AND comparison_op = '>'
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND rounding_places = 2
          AND currency = 'USD'
          AND source_policy -> 'sec' ->> 'form_type' = '8-K'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'sec' ->> 'document_type' = 'EX-99.1'
    ) <> 9 THEN
        RAISE EXCEPTION 'July 29 pre-market rule set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE (
            rule_key = 'hum-2026q2-nongaap-eps-7pt00'
            AND source_policy -> 'company_ir' ->> 'provider' =
                'company_ir'
        )
        OR (
            rule_key = 'wing-2026q2-gaap-eps-1pt03'
            AND source_policy ? 'company_ir'
            AND source_policy ? 'press_wire'
        )
        OR (
            rule_key = 'iart-2026q2-nongaap-eps-0pt48'
            AND source_policy ? 'company_ir'
            AND source_policy ? 'press_wire'
        )
        OR (
            rule_key = 'grmn-2026q2-nongaap-eps-2pt29'
            AND source_policy ? 'company_ir'
            AND source_policy ? 'press_wire'
        )
        OR (
            rule_key = 'cbre-2026q2-gaap-eps-1pt32'
            AND source_policy ? 'company_ir'
        )
        OR (
            rule_key = 'pag-2026q2-gaap-eps-3pt39'
            AND source_policy ? 'press_wire'
        )
    ) <> 6 THEN
        RAISE EXCEPTION 'July 29 public source set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'earnings-sofi-2026q2',
            'earnings-pg-2026q4',
            'earnings-hum-2026q2',
            'earnings-wing-2026q2',
            'earnings-arcc-2026q2',
            'earnings-iart-2026q2',
            'earnings-grmn-2026q2',
            'earnings-cbre-2026q2',
            'earnings-pag-2026q2'
        )
          AND status = 'DISABLED'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND prepare_from = TIMESTAMPTZ '2026-07-29 09:00:00+00'
          AND expires_at = TIMESTAMPTZ '2026-07-29 17:00:00+00'
    ) <> 9 THEN
        RAISE EXCEPTION 'July 29 pre-market profile set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE profile_key IN (
            'earnings-sofi-2026q2',
            'earnings-pg-2026q4',
            'earnings-hum-2026q2',
            'earnings-wing-2026q2',
            'earnings-arcc-2026q2',
            'earnings-iart-2026q2',
            'earnings-grmn-2026q2',
            'earnings-cbre-2026q2',
            'earnings-pag-2026q2'
        )
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at = TIMESTAMPTZ '2026-07-29 08:45:00+00'
          AND activate_at = TIMESTAMPTZ '2026-07-29 09:00:00+00'
          AND deactivate_at = TIMESTAMPTZ '2026-07-29 17:00:00+00'
          AND metadata ->> 'live_block' = 'PRE_MARKET'
          AND metadata ->> 'block_id' = '2026-07-29-pre-market'
    ) <> 9 THEN
        RAISE EXCEPTION 'July 29 pre-market schedule set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE ticker IN (
            'SOFI',
            'PG',
            'HUM',
            'WING',
            'ARCC',
            'IART',
            'GRMN',
            'CBRE',
            'PAG'
        )
          AND release_date = DATE '2026-07-29'
          AND market_session = 'PRE_MARKET'
          AND schedule_status = 'CONFIRMED'
          AND integration_status = 'PARSER_ONLY'
    ) <> 9 THEN
        RAISE EXCEPTION 'July 29 pre-market catalog mismatch';
    END IF;

    SELECT SUM(
        quantity * GREATEST(yes_desired_price, no_desired_price)
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-sofi-2026q2',
        'earnings-pg-2026q4',
        'earnings-hum-2026q2',
        'earnings-wing-2026q2',
        'earnings-arcc-2026q2',
        'earnings-iart-2026q2',
        'earnings-grmn-2026q2',
        'earnings-cbre-2026q2',
        'earnings-pag-2026q2'
    );

    IF reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'July 29 pre-market notional exceeds 1000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:SOFI:2026Q2',
            'earnings:PG:2026Q4',
            'earnings:HUM:2026Q2',
            'earnings:WING:2026Q2',
            'earnings:ARCC:2026Q2',
            'earnings:IART:2026Q2',
            'earnings:GRMN:2026Q2',
            'earnings:CBRE:2026Q2',
            'earnings:PAG:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'July 29 pre-market execution claim must not exist';
    END IF;
END
$verification$;

ROLLBACK;
