-- Idempotent public-data seed for the MSTR July 21-27 baseline.
-- No trading profile is created or enabled by this seed.

BEGIN;

DO $seed$
DECLARE
    existing mstr_btc_holdings_state%ROWTYPE;
BEGIN
    IF to_regclass('mstr_btc_holdings_state') IS NULL THEN
        RAISE EXCEPTION 'MSTR holdings schema is not ready';
    END IF;

    SELECT *
    INTO existing
    FROM mstr_btc_holdings_state
    WHERE provider = 'sec'
      AND provider_event_id = '0001193125-26-308369';

    IF FOUND THEN
        IF existing.holdings_btc IS DISTINCT FROM 843775
            OR existing.as_of IS DISTINCT FROM
                TIMESTAMPTZ '2026-07-19 00:00:00+00'
            OR existing.observed_at IS DISTINCT FROM
                TIMESTAMPTZ '2026-07-20 12:00:16+00'
            OR existing.source_url IS DISTINCT FROM
                'https://www.sec.gov/Archives/edgar/data/1050446/000119312526308369/mstr-20260720.htm'
            OR existing.document_fingerprint IS DISTINCT FROM
                'abc2e2494d982d961592ebf94d26f7ec1d83288f03e369e6daa1158f0d733e3f'
            OR existing.predecessor_state_id IS NOT NULL
            OR existing.validation_status IS DISTINCT FROM 'VALIDATED'
            OR existing.attributes IS DISTINCT FROM
                '{
                    "reported_as_of_date": "2026-07-19",
                    "as_of_precision": "date",
                    "filing_date": "2026-07-20",
                    "ticker": "MSTR",
                    "cik": "1050446"
                }'::jsonb
        THEN
            RAISE EXCEPTION 'existing MSTR baseline conflicts with seed';
        END IF;
    ELSE
        INSERT INTO mstr_btc_holdings_state (
            holdings_btc,
            as_of,
            observed_at,
            provider,
            provider_event_id,
            source_url,
            document_fingerprint,
            predecessor_state_id,
            validation_status,
            attributes
        )
        VALUES (
            843775,
            TIMESTAMPTZ '2026-07-19 00:00:00+00',
            TIMESTAMPTZ '2026-07-20 12:00:16+00',
            'sec',
            '0001193125-26-308369',
            'https://www.sec.gov/Archives/edgar/data/1050446/000119312526308369/mstr-20260720.htm',
            'abc2e2494d982d961592ebf94d26f7ec1d83288f03e369e6daa1158f0d733e3f',
            NULL,
            'VALIDATED',
            '{
                "reported_as_of_date": "2026-07-19",
                "as_of_precision": "date",
                "filing_date": "2026-07-20",
                "ticker": "MSTR",
                "cik": "1050446"
            }'::jsonb
        );
    END IF;
END
$seed$;

COMMIT;
