-- Fail-closed, read-only verification for observation-only earnings tails.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF to_regclass('earnings_source_race_observations') IS NULL THEN
        RAISE EXCEPTION 'earnings source race view is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = to_regclass(
            'earnings_fact_candidates'
        )
          AND conname =
              'earnings_fact_candidates_status_check'
          AND pg_get_constraintdef(oid) LIKE '%OBSERVED%'
    ) THEN
        RAISE EXCEPTION 'OBSERVED earnings fact status is missing';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name =
              'earnings_source_race_observations'
          AND column_name IN (
              'scope_id',
              'provider',
              'source_transport',
              'observation_mode',
              'fact_status',
              'transport_observed_at',
              'source_race_rank',
              'source_race_lag_ms',
              'winner_provider',
              'agrees_with_winner'
          )
    ) <> 10 THEN
        RAISE EXCEPTION 'earnings source race view is incomplete';
    END IF;
END
$verification$;

ROLLBACK;
