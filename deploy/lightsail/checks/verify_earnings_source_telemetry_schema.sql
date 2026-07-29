-- Verify additive source telemetry objects without returning event, ticker,
-- source, timing, account, order, or secret data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF to_regclass(
        'earnings_source_processing_telemetry'
    ) IS NULL THEN
        RAISE EXCEPTION
            'earnings processing telemetry table is not ready';
    END IF;

    IF to_regclass(
        'earnings_source_transport_observations'
    ) IS NULL THEN
        RAISE EXCEPTION
            'earnings transport observations table is not ready';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name =
              'earnings_source_processing_telemetry'
    ) <> 11 THEN
        RAISE EXCEPTION
            'earnings processing telemetry columns are not ready';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name =
              'earnings_source_transport_observations'
    ) <> 8 THEN
        RAISE EXCEPTION
            'earnings transport observation columns are not ready';
    END IF;

    IF to_regclass(
        'ux_earnings_source_transport_observations_event_transport'
    ) IS NULL THEN
        RAISE EXCEPTION
            'earnings transport observation index is not ready';
    END IF;

    IF to_regclass(
        'ix_earnings_source_processing_telemetry_transport'
    ) IS NULL THEN
        RAISE EXCEPTION
            'earnings processing telemetry index is not ready';
    END IF;
END
$verification$;

ROLLBACK;
