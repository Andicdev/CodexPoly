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
temporary_file="$(mktemp "${backup_directory}/.${environment_name}.XXXXXX")"
destination="${backup_directory}/codexpoly-${timestamp}.dump"

cleanup() {
    if [[ -n "${temporary_file:-}" && -e "${temporary_file}" ]]; then
        rm -f -- "${temporary_file}"
    fi
}
trap cleanup EXIT INT TERM

docker compose \
    -f "${compose_file}" \
    exec -T postgres \
    pg_dump \
    --username codexpoly_admin \
    --dbname codexpoly \
    --format custom \
    --no-owner \
    --file - >"${temporary_file}"

chmod 0600 "${temporary_file}"
mv -- "${temporary_file}" "${destination}"
temporary_file=""

find "${backup_directory}" \
    -type f \
    -name 'codexpoly-*.dump' \
    -mtime +14 \
    -delete

printf 'PostgreSQL backup completed for %s.\n' "${environment_name}"
