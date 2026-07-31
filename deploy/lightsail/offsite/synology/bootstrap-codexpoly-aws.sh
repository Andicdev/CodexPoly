#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    printf 'This bootstrap must run as root.\n' >&2
    exit 1
fi

setup_directory="/volume1/Backups/VPS/codexpoly-aws-setup"
setup_script="${setup_directory}/setup-backup-target.sh"
pull_source="${setup_directory}/pull-codexpoly-backups.sh"
age_installer="${setup_directory}/install-age.sh"

printf 'NAS architecture: %s\n' "$(uname -m)"
chmod 0755 "${age_installer}" "${setup_script}" "${pull_source}"
"${age_installer}"

"${setup_script}" \
    aws-codexpoly-host-01-eu-west-1 \
    52.16.49.33 \
    SHA256:4CZ4z74rwtFxrRvDdK1DfTqq+vZIbS+0+TOIJuON/Gc \
    "${setup_directory}/known_hosts.host01"

"${setup_script}" \
    aws-codexpoly-host-02-eu-west-1 \
    54.73.200.228 \
    SHA256:66DTi8lhpezeIBHoAdMCpbmOCxHQPxJ5hsxWP7u1vbc \
    "${setup_directory}/known_hosts.host02"

printf 'Synology AWS backup bootstrap completed.\n'
