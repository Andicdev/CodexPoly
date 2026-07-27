-- Add official Woodward REST listing and GlobeNewswire feed.
-- Profile status is deliberately unchanged. Safe to run repeatedly.

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
                    "www.woodward.com"
                ],
                "feed_url": "https://www.woodward.com/wp-json/wp/v2/press-release?per_page=10&orderby=date&order=desc&_fields=id,date_gmt,modified_gmt,link,slug,title",
                "kind": "wordpress_rest",
                "provider": "company_ir",
                "title_all": [
                    "Woodward",
                    "Third Quarter",
                    "Fiscal Year 2026",
                    "Results"
                ],
                "title_none": [
                    "conference call",
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
                    "Woodward",
                    "Third Quarter",
                    "Fiscal Year 2026",
                    "Results"
                ],
                "title_none": [
                    "conference call",
                    "to report"
                ]
            }
        }'::jsonb,
        updated_at = now()
    WHERE rule_key = 'wwd-2026q3-gaap-eps-2pt42'
      AND scope_id = 'earnings:WWD:2026Q3';

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION
            'expected one WWD earnings rule, updated %',
            changed_rows;
    END IF;
END
$migration$;

COMMIT;
