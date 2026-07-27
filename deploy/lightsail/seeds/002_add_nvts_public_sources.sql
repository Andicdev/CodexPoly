-- Add official IR and GlobeNewswire feeds without changing profile status.
-- Safe to run repeatedly.

BEGIN;

DO $migration$
DECLARE
    changed_rows integer;
BEGIN
    UPDATE earnings_market_rules
    SET
        source_policy = source_policy || '{
            "company_ir": {
                "allowed_document_hosts": [
                    "ir.navitassemi.com",
                    "navitassemi.gcs-web.com"
                ],
                "feed_url": "https://ir.navitassemi.com/rss/news-releases.xml",
                "kind": "rss",
                "provider": "company_ir",
                "title_all": [
                    "Navitas Semiconductor",
                    "Second Quarter 2026",
                    "Financial Results"
                ],
                "title_none": [
                    "to report"
                ]
            },
            "press_wire": {
                "allowed_document_hosts": [
                    "www.globenewswire.com"
                ],
                "feed_url": "https://www.globenewswire.com/RssFeed/subjectcode/13-Earnings%20Releases%20And%20Operating%20Results/feedTitle/GlobeNewswire%20-%20Earnings%20Releases%20And%20Operating%20Results",
                "kind": "rss",
                "provider": "globenewswire",
                "title_all": [
                    "Navitas Semiconductor",
                    "Second Quarter 2026",
                    "Financial Results"
                ],
                "title_none": [
                    "to report"
                ]
            }
        }'::jsonb,
        updated_at = now()
    WHERE rule_key = 'nvts-2026q2-nongaap-eps-neg0pt04'
      AND scope_id = 'earnings:NVTS:2026Q2';

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION
            'expected one NVTS earnings rule, updated %',
            changed_rows;
    END IF;
END
$migration$;

COMMIT;
