-- Schema-only invariant. The production runner suppresses row output.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF to_regclass('resolution_run_journal') IS NULL
       OR to_regclass('resolution_run_journal_events') IS NULL THEN
        RAISE EXCEPTION 'resolution run journal tables are missing';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_run_journal'
    ) <> 40 OR (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_run_journal_events'
    ) <> 11 THEN
        RAISE EXCEPTION 'resolution run journal column set mismatch';
    END IF;

    IF to_regclass('ux_resolution_run_journal_key') IS NULL
       OR to_regclass('ix_resolution_run_journal_scope') IS NULL
       OR to_regclass('ix_resolution_run_journal_result') IS NULL
       OR to_regclass('ix_resolution_run_journal_block') IS NULL
       OR to_regclass('ux_resolution_run_journal_events_key') IS NULL
       OR to_regclass(
           'ix_resolution_run_journal_events_timeline'
       ) IS NULL THEN
        RAISE EXCEPTION 'resolution run journal index set mismatch';
    END IF;
END
$verification$;

ROLLBACK;
