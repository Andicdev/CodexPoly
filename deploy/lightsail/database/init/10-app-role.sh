#!/usr/bin/env bash
set -euo pipefail

password_file="${DATABASE_APP_PASSWORD_FILE:-}"
if [[ -z "${password_file}" || ! -s "${password_file}" ]]; then
    printf 'DATABASE_APP_PASSWORD_FILE is unavailable.\n' >&2
    exit 1
fi

export DATABASE_APP_PASSWORD
DATABASE_APP_PASSWORD="$(<"${password_file}")"

if ! psql \
    --username "${POSTGRES_USER}" \
    --dbname "${POSTGRES_DB}" \
    --set=ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
\getenv app_password DATABASE_APP_PASSWORD
SELECT format(
    'CREATE ROLE codexpoly_app LOGIN NOSUPERUSER NOCREATEDB '
    'NOCREATEROLE NOINHERIT PASSWORD %L',
    :'app_password'
)
WHERE NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'codexpoly_app'
)
\gexec

SELECT format(
    'ALTER ROLE codexpoly_app LOGIN NOSUPERUSER NOCREATEDB '
    'NOCREATEROLE NOINHERIT PASSWORD %L',
    :'app_password'
)
\gexec
SQL
then
    printf 'APP_ROLE_PASSWORD_CONFIGURATION=failed\n' >&2
    exit 1
fi

if ! psql \
    --username "${POSTGRES_USER}" \
    --dbname "${POSTGRES_DB}" \
    --set=ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE codexpoly TO codexpoly_app;
GRANT USAGE ON SCHEMA public TO codexpoly_app;

ALTER DEFAULT PRIVILEGES
    FOR ROLE codexpoly_admin
    IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO codexpoly_app;

ALTER DEFAULT PRIVILEGES
    FOR ROLE codexpoly_admin
    IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO codexpoly_app;
SQL
then
    printf 'APP_ROLE_PRIVILEGE_CONFIGURATION=failed\n' >&2
    exit 1
fi

unset DATABASE_APP_PASSWORD
printf 'APP_ROLE_CONFIGURATION=ok\n'
