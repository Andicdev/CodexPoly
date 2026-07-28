-- Persist the remaining public July 29 Polymarket discovery as research
-- backlog. This seed creates no executable rule, profile, or schedule.

BEGIN;

WITH backlog (
    ticker,
    market_session,
    metric_kind,
    strike,
    market_slug,
    condition_id
) AS (
    VALUES
    (
        'WING',
        'PRE_MARKET',
        'gaap_eps',
        '1.03',
        'wing-quarterly-earnings-gaap-eps-07-29-2026-1pt03',
        '0x364b6da0b6c766eb072c3be8ded36b6fc39e5b8c831346fd2e277d2c1d07714a'
    ),
    (
        'ARCC',
        'PRE_MARKET',
        'non_gaap_eps',
        '0.47',
        'arcc-quarterly-earnings-nongaap-eps-07-29-2026-0pt47',
        '0xc1d7ebaa2951adedf0e111c0555e29426755d005dedb43ce71bf7d1c065a22b8'
    ),
    (
        'IART',
        'PRE_MARKET',
        'non_gaap_eps',
        '0.48',
        'iart-quarterly-earnings-nongaap-eps-07-29-2026-0pt48',
        '0x105f7e63b07c079be5e52a3c15ba8ce15022c45b189ea9a54d23c31bd972eb1f'
    ),
    (
        'GRMN',
        'PRE_MARKET',
        'non_gaap_eps',
        '2.29',
        'grmn-quarterly-earnings-nongaap-eps-07-29-2026-2pt29',
        '0xa8799cc9d0d491c736c76d6906e9cf9cf10913d285bcf50ca834ff4d50753116'
    ),
    (
        'CBRE',
        'PRE_MARKET',
        'gaap_eps',
        '1.32',
        'cbre-quarterly-earnings-gaap-eps-07-29-2026-1pt32',
        '0x27211249b8125a43a4b850ce763030142709ee1402ebac8b3a8543bee0cd9d22'
    ),
    (
        'PAG',
        'PRE_MARKET',
        'gaap_eps',
        '3.39',
        'pag-quarterly-earnings-gaap-eps-07-29-2026-3pt39',
        '0xdb3c1e0e76010fb23f1c29d2adf701c1e56eadc2d0d45282863296367ba64e71'
    ),
    (
        'ETSY',
        'PRE_MARKET',
        'gaap_eps',
        '0.72',
        'etsy-quarterly-earnings-gaap-eps-07-29-2026-0pt72',
        '0xd85d55793f1d99b82572825176521527f0c7144b9e9a40d25cd597f0c3ebcce1'
    ),
    (
        'SONO',
        'POST_MARKET',
        'non_gaap_eps',
        '0.20',
        'sono-quarterly-earnings-nongaap-eps-07-29-2026-0pt2',
        '0x7fcbdfbd6a6b450bd496003f052b818fa36e289e44d414eb7a1abf3dbf103c82'
    ),
    (
        'ARM',
        'POST_MARKET',
        'non_gaap_eps',
        '0.40',
        'arm-quarterly-earnings-nongaap-eps-07-29-2026-0pt4',
        '0x3c52b0977fc702234c2233483827be06e46a2b0e50e43200f876fa40bbfb4ad5'
    ),
    (
        'WAY',
        'POST_MARKET',
        'non_gaap_eps',
        '0.40',
        'way-quarterly-earnings-nongaap-eps-07-29-2026-0pt4',
        '0xaf07f668593362c55d734ec94a80b415bc12015b92cb03c4b8c5e571e018da2e'
    ),
    (
        'EA',
        'POST_MARKET',
        'gaap_eps',
        '0.80',
        'ea-quarterly-earnings-gaap-eps-07-29-2026-0pt8',
        '0x151d05bdd2378f36aeb2977402088824d5999a1c333a37182dcba7929004c3b6'
    ),
    (
        'MGM',
        'POST_MARKET',
        'non_gaap_eps',
        '0.60',
        'mgm-quarterly-earnings-nongaap-eps-07-29-2026-0pt6',
        '0xb5add19973c89018b5a90edd4b36fdbb09d77e7dbfe3938d3f491d640c9114ef'
    ),
    (
        'ORLY',
        'POST_MARKET',
        'gaap_eps',
        '0.86',
        'orly-quarterly-earnings-gaap-eps-07-29-2026-0pt86',
        '0xbee59b711f4a12ac673ff9279742b11eeaaa3cb71a00fbb5d18b4c9e7c6d87d7'
    ),
    (
        'TDOC',
        'POST_MARKET',
        'gaap_eps',
        '-0.25',
        'tdoc-quarterly-earnings-gaap-eps-07-29-2026-neg0pt25',
        '0x71d4b9d549d6fd1fb2f01840988b3f2ebe0abfcd764f3b075488e8d1d9f277c3'
    ),
    (
        'CMG',
        'POST_MARKET',
        'non_gaap_eps',
        '0.32',
        'cmg-quarterly-earnings-nongaap-eps-07-29-2026-0pt32',
        '0x4be61fd97343c46ae57b583c6779a392b17ebff171c3fdfeccc20ea666c0fa68'
    ),
    (
        'CVNA',
        'POST_MARKET',
        'gaap_eps',
        '0.42',
        'cvna-quarterly-earnings-gaap-eps-07-29-2026-0pt42',
        '0xd0b8e15ad33909bdab35607e94ec85faa02cf912ce4abe88bcc959eded281708'
    )
)
INSERT INTO earnings_release_catalog (
    event_key,
    ticker,
    release_date,
    market_session,
    scheduled_release_at,
    conference_call_at,
    schedule_status,
    schedule_source_url,
    integration_status,
    document_format,
    metric_options,
    source_options,
    notes,
    verified_at
)
SELECT
    ticker || ':2026-07-29',
    ticker,
    DATE '2026-07-29',
    market_session,
    NULL,
    NULL,
    'ESTIMATED',
    'https://polymarket.com/event/' || market_slug,
    'RESEARCH_PENDING',
    'UNKNOWN',
    jsonb_build_object(
        'comparison_op', '>',
        'market_basis', metric_kind,
        'market_slug', market_slug,
        'condition_id', condition_id,
        'primary_basis', 'diluted',
        'fallback_basis', 'basic',
        'strike', strike
    ),
    jsonb_build_array(
        jsonb_build_object(
            'delivery', 'websocket',
            'provider', 'sec',
            'status', 'needs_form_and_exhibit_review'
        )
    ),
    'Gamma market identity recorded; official schedule and parser pending.',
    now()
FROM backlog
ON CONFLICT (event_key) DO UPDATE
SET
    ticker = EXCLUDED.ticker,
    release_date = EXCLUDED.release_date,
    market_session = EXCLUDED.market_session,
    scheduled_release_at = EXCLUDED.scheduled_release_at,
    conference_call_at = EXCLUDED.conference_call_at,
    schedule_status = EXCLUDED.schedule_status,
    schedule_source_url = EXCLUDED.schedule_source_url,
    integration_status = EXCLUDED.integration_status,
    document_format = EXCLUDED.document_format,
    metric_options = EXCLUDED.metric_options,
    source_options = EXCLUDED.source_options,
    notes = EXCLUDED.notes,
    verified_at = EXCLUDED.verified_at,
    updated_at = now();

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE ticker IN (
            'WING',
            'ARCC',
            'IART',
            'GRMN',
            'CBRE',
            'PAG',
            'ETSY',
            'SONO',
            'ARM',
            'WAY',
            'EA',
            'MGM',
            'ORLY',
            'TDOC',
            'CMG',
            'CVNA'
        )
          AND release_date = DATE '2026-07-29'
          AND integration_status = 'RESEARCH_PENDING'
          AND metric_options ? 'market_slug'
          AND metric_options ? 'condition_id'
    ) <> 16 THEN
        RAISE EXCEPTION 'July 29 research backlog mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE metadata ->> 'ticker' IN (
            'WING',
            'ARCC',
            'IART',
            'GRMN',
            'CBRE',
            'PAG',
            'ETSY',
            'SONO',
            'ARM',
            'WAY',
            'EA',
            'MGM',
            'ORLY',
            'TDOC',
            'CMG',
            'CVNA'
        )
    ) THEN
        RAISE EXCEPTION 'research backlog must not create profiles';
    END IF;
END
$verification$;

COMMIT;
