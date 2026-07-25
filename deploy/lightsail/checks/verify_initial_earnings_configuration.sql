-- Read-only invariant check for the initial isolated staging database.
-- The migration runner suppresses PostgreSQL output; only success or failure
-- is reported to the caller.

BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    runtime_row_count bigint;
BEGIN
    IF to_regclass('earnings_market_rules') IS NULL
        OR to_regclass('earnings_source_events') IS NULL
        OR to_regclass('earnings_fact_candidates') IS NULL
        OR to_regclass('resolution_execution_profiles') IS NULL
        OR to_regclass('resolution_profile_templates') IS NULL
        OR to_regclass('resolution_execution_claims') IS NULL
    THEN
        RAISE EXCEPTION 'required staging schema is incomplete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                (
                    'nvts-2026q2-nongaap-eps-neg0pt04',
                    'earnings:NVTS:2026Q2',
                    'NVTS',
                    -0.04::numeric,
                    '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d'
                ),
                (
                    'wwd-2026q3-gaap-eps-2pt42',
                    'earnings:WWD:2026Q3',
                    'WWD',
                    2.42::numeric,
                    '0x4e84af80ebdd0c2e658c9b29f7a847289c758117d9d47382f3bfc5fb0df157ff'
                ),
                (
                    'bbby-2026q2-nongaap-eps-neg0pt26',
                    'earnings:BBBY:2026Q2',
                    'BBBY',
                    -0.26::numeric,
                    '0x2a6affd160ac8d394da6a12d8ff1479e20e1f6efa22e46001d82ea99665f1045'
                )
        ) AS expected(
            rule_key,
            scope_id,
            ticker,
            strike,
            condition_id
        )
        LEFT JOIN earnings_market_rules AS actual
          ON actual.rule_key = expected.rule_key
        WHERE actual.id IS NULL
           OR actual.scope_id IS DISTINCT FROM expected.scope_id
           OR actual.ticker IS DISTINCT FROM expected.ticker
           OR actual.strike IS DISTINCT FROM expected.strike
           OR actual.condition_id IS DISTINCT FROM expected.condition_id
           OR actual.status IS DISTINCT FROM 'SHADOW'
    ) THEN
        RAISE EXCEPTION 'initial earnings rules do not match';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            VALUES
                (
                    'earnings-nvts-2026q2',
                    'earnings:NVTS:2026Q2',
                    TIMESTAMPTZ '2026-07-27 19:00:00+00',
                    TIMESTAMPTZ '2026-07-28 03:00:00+00'
                ),
                (
                    'earnings-wwd-2026q3',
                    'earnings:WWD:2026Q3',
                    TIMESTAMPTZ '2026-07-29 18:00:00+00',
                    TIMESTAMPTZ '2026-07-30 02:00:00+00'
                ),
                (
                    'earnings-bbby-2026q2',
                    'earnings:BBBY:2026Q2',
                    TIMESTAMPTZ '2026-08-04 18:00:00+00',
                    TIMESTAMPTZ '2026-08-05 02:00:00+00'
                )
        ) AS expected(
            profile_key,
            scope_id,
            prepare_from,
            expires_at
        )
        LEFT JOIN resolution_execution_profiles AS actual
          ON actual.profile_key = expected.profile_key
        WHERE actual.id IS NULL
           OR actual.scope_id IS DISTINCT FROM expected.scope_id
           OR actual.account_name IS DISTINCT FROM 'abccbaq'
           OR actual.status IS DISTINCT FROM 'DISABLED'
           OR actual.source_name IS DISTINCT FROM 'earnings_resolution'
           OR actual.yes_desired_price IS DISTINCT FROM 0.999
           OR actual.no_desired_price IS DISTINCT FROM 0.999
           OR actual.quantity IS DISTINCT FROM 50
           OR actual.lifecycle_kind IS DISTINCT FROM
              'reprice_on_tick_change'
           OR actual.old_tick IS DISTINCT FROM 0.01
           OR actual.new_tick IS DISTINCT FROM 0.001
           OR actual.max_reprices IS DISTINCT FROM 1
           OR actual.prepare_from IS DISTINCT FROM expected.prepare_from
           OR actual.expires_at IS DISTINCT FROM expected.expires_at
    ) THEN
        RAISE EXCEPTION 'initial execution profiles do not match';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_profile_templates
        WHERE template_key = 'default'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 50
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
    ) THEN
        RAISE EXCEPTION 'default execution profile template does not match';
    END IF;

    SELECT
        (SELECT count(*) FROM earnings_source_events)
        + (SELECT count(*) FROM earnings_fact_candidates)
        + (SELECT count(*) FROM resolution_execution_claims)
    INTO runtime_row_count;

    IF runtime_row_count <> 0 THEN
        RAISE EXCEPTION 'runtime history was unexpectedly copied';
    END IF;
END
$verify$;

ROLLBACK;
