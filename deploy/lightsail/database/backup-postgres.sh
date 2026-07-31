#!/usr/bin/env bash
set -euo pipefail

environment_name="${1:-}"
case "${environment_name}" in
    staging)
        compose_file="/opt/codexpoly/staging/apps/database/compose.yml"
        backup_directory="/opt/codexpoly/staging/backups/postgres"
        ;;
    production)
        compose_file="/opt/codexpoly/production/apps/database/compose.yml"
        backup_directory="/opt/codexpoly/backups/postgres/production"
        ;;
    *)
        printf 'Usage: %s staging|production\n' "$0" >&2
        exit 2
        ;;
esac

umask 077
install -d -m 0700 "${backup_directory}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary_file=""
configured_databases="${CODEXPOLY_BACKUP_DATABASES:-codexpoly codexpoly_neg_risk}"
read -r -a database_names <<<"${configured_databases}"
readonly database_names

if (( ${#database_names[@]} == 0 )); then
    printf 'No PostgreSQL databases configured for backup.\n' >&2
    exit 2
fi

for database_name in "${database_names[@]}"; do
    if [[ ! "${database_name}" =~ ^[a-z][a-z0-9_]*$ ]]; then
        printf 'Invalid PostgreSQL database name in backup configuration.\n' >&2
        exit 2
    fi
done

cleanup() {
    if [[ -n "${temporary_file:-}" && -e "${temporary_file}" ]]; then
        rm -f -- "${temporary_file}"
    fi
}
trap cleanup EXIT INT TERM

for database_name in "${database_names[@]}"; do
    temporary_file="$(
        mktemp \
            "${backup_directory}/.${environment_name}-${database_name}.XXXXXX"
    )"
    destination="${backup_directory}/${database_name}-${timestamp}.dump"

    docker compose \
        -f "${compose_file}" \
        exec -T postgres \
        pg_dump \
        --username codexpoly_admin \
        --dbname "${database_name}" \
        --format custom \
        --no-owner >"${temporary_file}"

    if [[ ! -s "${temporary_file}" ]]; then
        printf 'PostgreSQL backup is empty for %s (%s).\n' \
            "${environment_name}" "${database_name}" >&2
        exit 1
    fi

    chmod 0600 "${temporary_file}"
    mv -- "${temporary_file}" "${destination}"
    temporary_file=""
done

find "${backup_directory}" \
    -type f \
    -name 'codexpoly*.dump' \
    -mtime +14 \
    -delete

printf 'PostgreSQL backup completed for %s.\n' "${environment_name}"
