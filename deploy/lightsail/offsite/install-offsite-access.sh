#!/usr/bin/env bash
set -euo pipefail

if (( $# != 4 )); then
    printf 'Usage: %s HOST_LABEL "DATABASES" TRANSFER_PUBLIC_KEY AGE_RECIPIENT\n' "$0" >&2
    exit 2
fi

readonly host_label="$1"
readonly configured_databases="$2"
readonly transfer_public_key_file="$3"
readonly age_recipient_source="$4"
readonly backup_user="nasbackup"
readonly backup_group="nasbackup"
readonly backup_home="/var/lib/nasbackup"
readonly offsite_directory="/var/backups/codexpoly/offsite"
readonly config_directory="/etc/codexpoly/offsite-backup"

if [[ "${EUID}" -ne 0 ]]; then
    printf 'This installer must run as root.\n' >&2
    exit 1
fi
if [[ ! "${host_label}" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    printf 'Invalid host label.\n' >&2
    exit 2
fi
read -r -a database_names <<<"${configured_databases}"
if (( ${#database_names[@]} == 0 )); then
    printf 'At least one database must be configured.\n' >&2
    exit 2
fi
for database_name in "${database_names[@]}"; do
    if [[ ! "${database_name}" =~ ^[a-z][a-z0-9_]*$ ]]; then
        printf 'Invalid database name.\n' >&2
        exit 2
    fi
done
if [[ ! -r "${transfer_public_key_file}" ]]; then
    printf 'Transfer public key file is unavailable.\n' >&2
    exit 1
fi
if ! ssh-keygen -l -f "${transfer_public_key_file}" >/dev/null; then
    printf 'Transfer public key is invalid.\n' >&2
    exit 1
fi
if [[ ! -r "${age_recipient_source}" ]]; then
    printf 'Age recipient file is unavailable.\n' >&2
    exit 1
fi
if [[ "$(grep -Ec '^age1[0-9a-z]+$' "${age_recipient_source}")" -ne 1 ]]; then
    printf 'Age recipient file is invalid.\n' >&2
    exit 1
fi
if ! command -v age >/dev/null; then
    printf 'age is not installed.\n' >&2
    exit 1
fi
if [[ ! -x /usr/bin/rrsync ]]; then
    printf 'rrsync is unavailable.\n' >&2
    exit 1
fi

if ! getent group "${backup_group}" >/dev/null; then
    groupadd --system "${backup_group}"
fi
if ! getent passwd "${backup_user}" >/dev/null; then
    useradd \
        --system \
        --gid "${backup_group}" \
        --home-dir "${backup_home}" \
        --create-home \
        --shell /bin/bash \
        "${backup_user}"
fi
passwd --lock "${backup_user}" >/dev/null

install -d -m 0700 -o "${backup_user}" -g "${backup_group}" \
    "${backup_home}/.ssh"
transfer_public_key="$(sed -n '1p' "${transfer_public_key_file}")"
authorized_keys_temp="$(mktemp)"
trap 'rm -f -- "${authorized_keys_temp}"' EXIT INT TERM
printf 'restrict,command="/usr/bin/rrsync -ro %s" %s\n' \
    "${offsite_directory}" "${transfer_public_key}" \
    >"${authorized_keys_temp}"
install -m 0600 -o "${backup_user}" -g "${backup_group}" \
    "${authorized_keys_temp}" "${backup_home}/.ssh/authorized_keys"

install -d -m 0750 -o root -g "${backup_group}" "${offsite_directory}"
install -d -m 0755 -o root -g root "${config_directory}"
install -m 0644 -o root -g root \
    "${age_recipient_source}" "${config_directory}/recipient.txt"

config_temp="$(mktemp)"
trap 'rm -f -- "${authorized_keys_temp}" "${config_temp}"' EXIT INT TERM
{
    printf 'HOST_LABEL=%q\n' "${host_label}"
    printf 'CODEXPOLY_BACKUP_DATABASES=%q\n' "${configured_databases}"
    printf 'AGE_RECIPIENT_FILE=%q\n' "${config_directory}/recipient.txt"
    printf 'MAX_SOURCE_AGE_MINUTES=1440\n'
    printf 'OFFSITE_RETENTION_DAYS=60\n'
} >"${config_temp}"
install -m 0644 -o root -g root \
    "${config_temp}" "${config_directory}/production.conf"

if sshd -T | awk '$1 == "allowusers" { found = 1 } END { exit !found }'; then
    if ! sshd -T | awk '$1 == "allowusers" && $2 == "nasbackup" { found = 1 } END { exit !found }'; then
        printf 'AllowUsers nasbackup\n' \
            >/etc/ssh/sshd_config.d/96-codexpoly-nasbackup.conf
        chmod 0644 /etc/ssh/sshd_config.d/96-codexpoly-nasbackup.conf
    fi
fi
sshd -t
systemctl reload ssh.service

printf 'Restricted offsite backup access installed for %s.\n' "${host_label}"
