#!/usr/bin/env bash
set -euo pipefail

environment_name="${1:-}"
if [[ "${environment_name}" != "production" ]]; then
    printf 'Usage: %s production\n' "$0" >&2
    exit 2
fi

readonly config_file="/etc/codexpoly/offsite-backup/production.conf"
readonly source_directory="/opt/codexpoly/backups/postgres/production"
readonly compose_file="/opt/codexpoly/production/apps/database/compose.yml"
readonly offsite_directory="/var/backups/codexpoly/offsite"

if [[ ! -r "${config_file}" ]]; then
    printf 'Offsite backup configuration is unavailable.\n' >&2
    exit 1
fi

# The configuration contains only non-secret settings and an age recipient
# file path. The corresponding private identity must never exist on the VPS.
# shellcheck source=/dev/null
source "${config_file}"

: "${HOST_LABEL:?HOST_LABEL is required}"
: "${CODEXPOLY_BACKUP_DATABASES:?CODEXPOLY_BACKUP_DATABASES is required}"
: "${AGE_RECIPIENT_FILE:?AGE_RECIPIENT_FILE is required}"
readonly max_source_age_minutes="${MAX_SOURCE_AGE_MINUTES:-1440}"

if [[ ! "${HOST_LABEL}" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    printf 'Invalid offsite backup host label.\n' >&2
    exit 2
fi
if [[ ! "${max_source_age_minutes}" =~ ^[1-9][0-9]*$ ]]; then
    printf 'Invalid maximum source backup age.\n' >&2
    exit 2
fi
if [[ ! -r "${AGE_RECIPIENT_FILE}" ]]; then
    printf 'The age recipient file is unavailable.\n' >&2
    exit 1
fi
if [[ "$(grep -Ec '^age1[0-9a-z]+$' "${AGE_RECIPIENT_FILE}")" -ne 1 ]]; then
    printf 'The age recipient file must contain exactly one recipient.\n' >&2
    exit 1
fi

read -r -a database_names <<<"${CODEXPOLY_BACKUP_DATABASES}"
readonly database_names
if (( ${#database_names[@]} == 0 )); then
    printf 'No PostgreSQL databases configured for offsite backup.\n' >&2
    exit 2
fi

declare -A source_files=()
source_timestamp=""
for database_name in "${database_names[@]}"; do
    if [[ ! "${database_name}" =~ ^[a-z][a-z0-9_]*$ ]]; then
        printf 'Invalid PostgreSQL database name in offsite configuration.\n' >&2
        exit 2
    fi

    latest_record="$(
        find "${source_directory}" \
            -maxdepth 1 \
            -type f \
            -name "${database_name}-*.dump" \
            -size +0c \
            -printf '%T@ %p\n' |
            sort -nr |
            sed -n '1p'
    )"
    latest_file="${latest_record#* }"
    if [[ -z "${latest_record}" || ! -f "${latest_file}" ]]; then
        printf 'No non-empty source dump for %s.\n' "${database_name}" >&2
        exit 1
    fi
    if ! find "${latest_file}" \
        -maxdepth 0 \
        -mmin "-${max_source_age_minutes}" \
        -print -quit |
        grep -q .; then
        printf 'The source dump for %s is stale.\n' "${database_name}" >&2
        exit 1
    fi

    source_basename="$(basename -- "${latest_file}")"
    if [[ ! "${source_basename}" =~ ^${database_name}-([0-9]{8}T[0-9]{6}Z)\.dump$ ]]; then
        printf 'Unexpected source dump name for %s.\n' "${database_name}" >&2
        exit 1
    fi
    database_timestamp="${BASH_REMATCH[1]}"
    if [[ -z "${source_timestamp}" ]]; then
        source_timestamp="${database_timestamp}"
    elif [[ "${database_timestamp}" != "${source_timestamp}" ]]; then
        printf 'Configured source dumps do not belong to one backup run.\n' >&2
        exit 1
    fi

    docker compose \
        --file "${compose_file}" \
        exec -T postgres \
        pg_restore --list <"${latest_file}" >/dev/null
    source_files["${database_name}"]="${latest_file}"
done

install -d -m 0750 -o root -g nasbackup "${offsite_directory}"
final_directory="${offsite_directory}/${source_timestamp}"
incomplete_directory="${offsite_directory}/.incomplete-${source_timestamp}"

if [[ -f "${final_directory}/COMPLETE" ]]; then
    printf 'Offsite backup is already staged for %s.\n' "${source_timestamp}"
    exit 0
fi
if [[ -e "${final_directory}" || -e "${incomplete_directory}" ]]; then
    printf 'An incomplete offsite backup path already exists.\n' >&2
    exit 1
fi

cleanup() {
    if [[
        -n "${incomplete_directory:-}" &&
        "${incomplete_directory}" == "${offsite_directory}"/.incomplete-* &&
        -d "${incomplete_directory}"
    ]]; then
        rm -rf -- "${incomplete_directory}"
    fi
}
trap cleanup EXIT INT TERM

umask 077
install -d -m 0750 -o root -g nasbackup "${incomplete_directory}"

for database_name in "${database_names[@]}"; do
    age \
        --encrypt \
        --recipients-file "${AGE_RECIPIENT_FILE}" \
        --output "${incomplete_directory}/${database_name}.dump.age" \
        "${source_files[${database_name}]}"
done

{
    printf 'format=postgresql-custom\n'
    printf 'source_timestamp=%s\n' "${source_timestamp}"
    for database_name in "${database_names[@]}"; do
        printf 'database=%s\n' "${database_name}"
    done
} >"${incomplete_directory}/DATABASE_MANIFEST"

{
    printf 'host=%s\n' "${HOST_LABEL}"
    printf 'created_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'encryption=age\n'
    printf 'payload=postgresql-dumps-only\n'
} >"${incomplete_directory}/OFFSITE_MANIFEST"

(
    cd "${incomplete_directory}"
    sha256sum -- *.age DATABASE_MANIFEST OFFSITE_MANIFEST >SHA256SUMS
    sha256sum --check SHA256SUMS >/dev/null
)

touch "${incomplete_directory}/COMPLETE"
chown -R root:nasbackup "${incomplete_directory}"
find "${incomplete_directory}" -type d -exec chmod 0750 {} +
find "${incomplete_directory}" -type f -exec chmod 0640 {} +
mv -- "${incomplete_directory}" "${final_directory}"
incomplete_directory=""
ln -sfn "${source_timestamp}" "${offsite_directory}/latest"
chown -h root:nasbackup "${offsite_directory}/latest"

printf 'Encrypted offsite backup staged for %s.\n' "${source_timestamp}"
