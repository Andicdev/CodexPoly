#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    printf 'Usage: %s TARGET_NAME\n' "$0" >&2
    exit 2
fi

target_name="$1"
config_directory="/root/.config/vps-backup/${target_name}"
config_file="${config_directory}/pull.conf"
base_directory="/volume1/Backups/VPS/${target_name}"
backup_directory="${base_directory}/backups"
log_directory="${base_directory}/logs"
lock_directory="${config_directory}/pull.lock"

if [ "$(id -u)" -ne 0 ]; then
    printf 'This pull script must run as root.\n' >&2
    exit 1
fi
if [ ! -r "${config_file}" ]; then
    printf 'Backup target configuration is unavailable.\n' >&2
    exit 1
fi

# shellcheck source=/dev/null
. "${config_file}"
: "${TARGET_NAME:?TARGET_NAME is required}"
: "${REMOTE_HOST:?REMOTE_HOST is required}"
: "${REMOTE_PORT:?REMOTE_PORT is required}"
: "${REMOTE_USER:?REMOTE_USER is required}"
: "${SSH_BINARY:?SSH_BINARY is required}"
: "${RSYNC_BINARY:?RSYNC_BINARY is required}"
: "${SHA256_BINARY:?SHA256_BINARY is required}"

if [ "${TARGET_NAME}" != "${target_name}" ]; then
    printf 'Backup target configuration mismatch.\n' >&2
    exit 1
fi

umask 077
mkdir -p "${backup_directory}" "${log_directory}"
chmod 0700 "${base_directory}" "${backup_directory}" "${log_directory}"
if ! mkdir "${lock_directory}" 2>/dev/null; then
    printf 'Another pull is already running for %s.\n' "${target_name}" >&2
    exit 1
fi
trap 'rmdir "${lock_directory}" 2>/dev/null || true' EXIT INT TERM

log_file="${log_directory}/pull-$(date +%Y%m).txt"
log() {
    printf '%s target=%s %s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "${target_name}" "$*" >>"${log_file}"
}

log 'status=start'
ssh_command="${SSH_BINARY} -p ${REMOTE_PORT} -i ${config_directory}/transfer_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=yes -o HostKeyAlgorithms=ssh-ed25519 -o UserKnownHostsFile=${config_directory}/known_hosts"

if ! "${RSYNC_BINARY}" \
    --archive \
    --partial \
    --delay-updates \
    --chmod=F600,D700 \
    --rsh="${ssh_command}" \
    "${REMOTE_USER}@${REMOTE_HOST}:/" \
    "${backup_directory}/" >>"${log_file}" 2>&1; then
    log 'status=failed stage=rsync'
    exit 1
fi

verification_failed=0
for candidate in "${backup_directory}"/*; do
    [ -d "${candidate}" ] || continue
    candidate_name="$(basename "${candidate}")"
    case "${candidate_name}" in
        [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z)
            ;;
        *)
            continue
            ;;
    esac
    [ -f "${candidate}/COMPLETE" ] || continue
    [ ! -e "${candidate}/VERIFIED" ] || continue
    if (
        cd "${candidate}"
        "${SHA256_BINARY}" --check SHA256SUMS >/dev/null
    ); then
        : >"${candidate}/VERIFIED"
        chmod 0600 "${candidate}/VERIFIED"
        log "status=verified backup=${candidate_name}"
    else
        log "status=failed stage=checksum backup=${candidate_name}"
        verification_failed=1
    fi
done

if [ "${verification_failed}" -ne 0 ]; then
    exit 1
fi
log 'status=complete'
