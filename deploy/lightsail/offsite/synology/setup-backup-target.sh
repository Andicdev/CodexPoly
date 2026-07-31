#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
    printf 'Usage: %s TARGET_NAME REMOTE_HOST EXPECTED_FINGERPRINT KNOWN_HOSTS_FILE\n' "$0" >&2
    exit 2
fi

target_name="$1"
remote_host="$2"
expected_fingerprint="$3"
known_hosts_source="$4"
config_directory="/root/.config/vps-backup/${target_name}"
backup_directory="/volume1/Backups/VPS/${target_name}"

if [ "$(id -u)" -ne 0 ]; then
    printf 'This setup script must run as root.\n' >&2
    exit 1
fi
case "${target_name}" in
    *[!a-z0-9-]*|'')
        printf 'Invalid backup target name.\n' >&2
        exit 2
        ;;
esac

find_tool() {
    tool_name="$1"
    for candidate in \
        "/usr/local/bin/${tool_name}" \
        "/opt/bin/${tool_name}" \
        "/usr/bin/${tool_name}" \
        "/bin/${tool_name}"
    do
        if [ -x "${candidate}" ]; then
            printf '%s\n' "${candidate}"
            return 0
        fi
    done
    return 1
}

require_tool() {
    required_tool="$1"
    if ! required_path="$(find_tool "${required_tool}")"; then
        printf 'Missing required tool: %s\n' "${required_tool}" >&2
        exit 1
    fi
    printf '%s\n' "${required_path}"
}

ssh_keygen="$(require_tool ssh-keygen)"
age_keygen="$(require_tool age-keygen)"
ssh_binary="$(require_tool ssh)"
rsync_binary="$(require_tool rsync)"
sha256_binary="$(require_tool sha256sum)"

umask 077
mkdir -p "${config_directory}"
mkdir -p \
    "${backup_directory}/backups" \
    "${backup_directory}/logs" \
    "${backup_directory}/setup"
chmod 0700 "${config_directory}"
chmod 0700 \
    "${backup_directory}" \
    "${backup_directory}/backups" \
    "${backup_directory}/logs" \
    "${backup_directory}/setup"

if [ ! -f "${config_directory}/transfer_ed25519" ]; then
    "${ssh_keygen}" \
        -q -t ed25519 -N '' \
        -C "${target_name}-nas-transfer" \
        -f "${config_directory}/transfer_ed25519"
fi
if [ ! -f "${config_directory}/encryption_ed25519" ]; then
    "${age_keygen}" \
        -o "${config_directory}/encryption_ed25519" \
        >/dev/null 2>&1
fi

cp "${known_hosts_source}" "${config_directory}/known_hosts"
chmod 0600 "${config_directory}/known_hosts"
actual_fingerprint="$("${ssh_keygen}" -lf "${config_directory}/known_hosts" | awk '{print $2}')"
if [ "${actual_fingerprint}" != "${expected_fingerprint}" ]; then
    printf 'Pinned SSH host fingerprint does not match.\n' >&2
    exit 1
fi

"${age_keygen}" -y "${config_directory}/encryption_ed25519" \
    >"${backup_directory}/setup/encryption_recipient.txt"
cp "${config_directory}/transfer_ed25519.pub" \
    "${backup_directory}/setup/transfer_ed25519.pub"
cp "${config_directory}/transfer_ed25519.pub" \
    "${backup_directory}/setup/transfer_ed25519_public.txt"
chmod 0600 \
    "${backup_directory}/setup/transfer_ed25519.pub" \
    "${backup_directory}/setup/transfer_ed25519_public.txt"

cat >"${config_directory}/pull.conf" <<EOF
TARGET_NAME=${target_name}
REMOTE_HOST=${remote_host}
REMOTE_PORT=22
REMOTE_USER=nasbackup
SSH_BINARY=${ssh_binary}
RSYNC_BINARY=${rsync_binary}
SHA256_BINARY=${sha256_binary}
RETENTION_DAYS=60
EOF
chmod 0600 "${config_directory}/pull.conf"

printf 'Synology backup target prepared: %s\n' "${target_name}"
