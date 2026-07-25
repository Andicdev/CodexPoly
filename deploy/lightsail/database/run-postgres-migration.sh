#!/usr/bin/env bash
set -euo pipefail

readonly max_sql_bytes=5242880

if [[ "$#" -ne 1 ]]; then
    printf 'MIGRATION_RESULT=rejected\nMIGRATION_REASON=invalid-runner-arguments\n' >&2
    exit 2
fi

environment="$1"
case "${environment}" in
    staging)
        if [[ "$(id -un)" != "codexdeploy" ]]; then
            printf 'MIGRATION_RESULT=rejected\nMIGRATION_REASON=invalid-staging-user\n' >&2
            exit 2
        fi
        readonly container=codexpoly-staging-db-postgres-1
        readonly user_id="$(id -u)"
        docker_command=(
            /usr/bin/docker
            --host "unix:///run/user/${user_id}/docker.sock"
        )
        ;;
    production)
        if [[ "${EUID}" -ne 0 ]]; then
            printf 'MIGRATION_RESULT=rejected\nMIGRATION_REASON=production-requires-root-runner\n' >&2
            exit 2
        fi
        readonly container=codexpoly-production-db-postgres-1
        docker_command=(
            /usr/bin/docker
            --host unix:///var/run/docker.sock
        )
        ;;
    *)
        printf 'MIGRATION_RESULT=rejected\nMIGRATION_REASON=unknown-environment\n' >&2
        exit 2
        ;;
esac

if [[ -t 0 ]]; then
    printf 'MIGRATION_RESULT=rejected\nMIGRATION_REASON=stdin-required\n' >&2
    exit 2
fi

umask 077
runtime_directory="$(mktemp -d /tmp/codexpoly-migration.XXXXXX)"
readonly runtime_directory
readonly sql_file="${runtime_directory}/migration.sql"
readonly result_file="${runtime_directory}/psql.result"

cleanup() {
    rm -f -- "${sql_file}" "${result_file}"
    rmdir -- "${runtime_directory}" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

/usr/bin/head -c "$((max_sql_bytes + 1))" >"${sql_file}"
sql_bytes="$(/usr/bin/stat -c '%s' "${sql_file}")"

if [[ "${sql_bytes}" -eq 0 ]]; then
    printf 'MIGRATION_RESULT=rejected\nMIGRATION_REASON=empty-input\n' >&2
    exit 2
fi

if [[ "${sql_bytes}" -gt "${max_sql_bytes}" ]]; then
    printf 'MIGRATION_RESULT=rejected\nMIGRATION_REASON=input-too-large\n' >&2
    exit 2
fi

if /usr/bin/grep -Eq '^[[:space:]]*\\' "${sql_file}"; then
    printf 'MIGRATION_RESULT=rejected\nMIGRATION_REASON=psql-meta-command\n' >&2
    exit 2
fi

if ! "${docker_command[@]}" exec \
    --user postgres \
    -i \
    "${container}" \
    psql \
    --no-psqlrc \
    --username codexpoly_admin \
    --dbname codexpoly \
    --set=ON_ERROR_STOP=1 \
    --set=VERBOSITY=terse \
    --file - \
    <"${sql_file}" \
    >"${result_file}" 2>&1
then
    printf 'MIGRATION_ENVIRONMENT=%s\nMIGRATION_RESULT=failed\n' \
        "${environment}" >&2
    exit 1
fi

printf 'MIGRATION_ENVIRONMENT=%s\nMIGRATION_RESULT=applied\n' \
    "${environment}"
