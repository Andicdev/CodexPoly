-- Fail closed unless additive migrations 021 and 022 are fully installed.
-- Returns no application rows or values.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF to_regclass('earnings_source_parse_attempts') IS NULL THEN
        RAISE EXCEPTION
            'earnings parser attempt table is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ux_earnings_source_parse_attempts_version'
        )
          AND indisunique
    ) THEN
        RAISE EXCEPTION
            'earnings parser attempt uniqueness is missing';
    END IF;

    IF (
        SELECT count(*) = 11
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'earnings_source_parse_attempts'
          AND column_name IN (
              'id',
              'source_event_id',
              'parser_name',
              'parser_version',
              'status',
              'attempt_count',
              'reason',
              'claimed_at',
              'completed_at',
              'created_at',
              'updated_at'
          )
    ) IS NOT TRUE THEN
        RAISE EXCEPTION
            'earnings parser attempt columns are incomplete';
    END IF;

    IF to_regclass(
        'resolution_order_group_terminal_audits'
    ) IS NULL THEN
        RAISE EXCEPTION
            'order-group terminal audit table is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass(
            'ix_resolution_order_group_terminal_audits_kind'
        )
    ) THEN
        RAISE EXCEPTION
            'order-group terminal audit index is missing';
    END IF;

    IF (
        SELECT count(*) = 10
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name =
              'resolution_order_group_terminal_audits'
          AND column_name IN (
              'order_group_id',
              'event_id',
              'terminal_kind',
              'target_quantity',
              'filled_quantity',
              'excess_quantity',
              'detected_at',
              'metadata',
              'created_at',
              'updated_at'
          )
    ) IS NOT TRUE THEN
        RAISE EXCEPTION
            'order-group terminal audit columns are incomplete';
    END IF;
END
$verification$;

ROLLBACK;
