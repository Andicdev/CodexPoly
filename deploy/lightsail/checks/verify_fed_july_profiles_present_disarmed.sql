-- Confirm that all five reviewed July FOMC profiles exist while remaining
-- unable to trade. This check exposes no profile, account, or market data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'fed-jul29-no-change',
            'fed-jul29-increase-25',
            'fed-jul29-increase-50-plus',
            'fed-jul29-decrease-25',
            'fed-jul29-decrease-50-plus'
        )
          AND source_name = 'fed_fomc'
          AND status = 'DISABLED'
    ) <> 5 THEN
        RAISE EXCEPTION
            'complete disarmed FED July profile set is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'fed:fomc:2026-07-29:%'
    ) THEN
        RAISE EXCEPTION 'FED July execution claim already exists';
    END IF;
END
$verification$;

ROLLBACK;
