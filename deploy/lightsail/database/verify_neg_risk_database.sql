DO $verification$
BEGIN
    IF current_database() <> 'codexpoly_neg_risk' THEN
        RAISE EXCEPTION 'unexpected database target';
    END IF;

    IF NOT has_database_privilege(
        'codexpoly_app',
        current_database(),
        'CONNECT'
    ) THEN
        RAISE EXCEPTION 'runtime role cannot connect';
    END IF;

    IF NOT has_schema_privilege('codexpoly_app', 'public', 'USAGE') THEN
        RAISE EXCEPTION 'runtime role cannot use public schema';
    END IF;

    IF has_schema_privilege('codexpoly_app', 'public', 'CREATE') THEN
        RAISE EXCEPTION 'runtime role can create schema objects';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname NOT IN (
            'information_schema',
            'pg_catalog',
            'pg_toast'
        )
          AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
    ) THEN
        RAISE EXCEPTION 'application schema is not empty';
    END IF;
END
$verification$;
