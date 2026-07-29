-- Verify the original July 29 post-market SEC-only subset.
-- The pre-market profiles moved to the richer guarded check in
-- verify_july_29_premarket_profiles.sql.

BEGIN TRANSACTION READ ONLY;

DO $verification$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key IN (
            'qcom-2026q3-nongaap-eps-2pt23',
            'msft-2026q4-gaap-eps-4pt21',
            'meta-2026q2-gaap-eps-7pt20',
            'ebay-2026q2-nongaap-eps-1pt51',
            'hood-2026q2-gaap-eps-0pt43'
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
          AND NOT source_policy ? 'company_ir'
          AND NOT source_policy ? 'press_wire'
    ) <> 5 THEN
        RAISE EXCEPTION 'July 29 post-market SEC rule set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'earnings-qcom-2026q3',
            'earnings-msft-2026q4',
            'earnings-meta-2026q2',
            'earnings-ebay-2026q2',
            'earnings-hood-2026q2'
        )
          AND status = 'DISABLED'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 50
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
    ) <> 5 THEN
        RAISE EXCEPTION
            'July 29 post-market execution profile set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE profile_key IN (
            'earnings-qcom-2026q3',
            'earnings-msft-2026q4',
            'earnings-meta-2026q2',
            'earnings-ebay-2026q2',
            'earnings-hood-2026q2'
        )
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND metadata ->> 'live_block' = 'POST_MARKET'
          AND metadata ->> 'block_id' =
              '2026-07-29-post-market'
    ) <> 5 THEN
        RAISE EXCEPTION
            'July 29 post-market schedule set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key IN (
            'QCOM:2026-07-29',
            'MSFT:2026-07-29',
            'META:2026-07-29',
            'EBAY:2026-07-29',
            'HOOD:2026-07-29'
        )
          AND integration_status = 'PARSER_ONLY'
          AND metric_options ->> 'comparison_op' = '>'
          AND metric_options ->> 'primary_basis' = 'diluted'
          AND source_options @>
              '[{"delivery":"websocket","provider":"sec","status":"available"}]'::jsonb
    ) <> 5 THEN
        RAISE EXCEPTION
            'July 29 post-market release catalog set mismatch';
    END IF;

    SELECT SUM(
        quantity * GREATEST(yes_desired_price, no_desired_price)
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-qcom-2026q3',
        'earnings-msft-2026q4',
        'earnings-meta-2026q2',
        'earnings-ebay-2026q2',
        'earnings-hood-2026q2'
    );

    IF reviewed_notional > 1000 THEN
        RAISE EXCEPTION
            'July 29 post-market reviewed notional exceeds 1000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:QCOM:2026Q3',
            'earnings:MSFT:2026Q4',
            'earnings:META:2026Q2',
            'earnings:EBAY:2026Q2',
            'earnings:HOOD:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION
            'July 29 post-market execution claim must not exist';
    END IF;
END
$verification$;

ROLLBACK;
