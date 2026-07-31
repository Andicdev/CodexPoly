#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    printf 'This installer must run as root.\n' >&2
    exit 1
fi

setup_directory="/volume1/Backups/VPS/codexpoly-aws-setup"
archive="${setup_directory}/codexpoly-age-v1.3.1-linux-amd64.tar.gz"
expected_sha256="bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377"
extract_directory="${setup_directory}/age-v1.3.1-linux-amd64"
binary_directory="/usr/local/bin"

if [ -x "${binary_directory}/age" ] && [ -x "${binary_directory}/age-keygen" ]; then
    exit 0
fi

if [ "$(uname -m)" != "x86_64" ]; then
    printf 'Unsupported NAS architecture for bundled age release.\n' >&2
    exit 1
fi
if [ ! -f "${archive}" ]; then
    printf 'Missing verified age release archive.\n' >&2
    exit 1
fi

actual_sha256="$(sha256sum "${archive}" | awk '{print $1}')"
if [ "${actual_sha256}" != "${expected_sha256}" ]; then
    printf 'age release checksum mismatch.\n' >&2
    exit 1
fi

mkdir -p "${extract_directory}" "${binary_directory}"
tar -xzf "${archive}" -C "${extract_directory}"
cp "${extract_directory}/age/age" "${binary_directory}/age"
cp "${extract_directory}/age/age-keygen" "${binary_directory}/age-keygen"
chmod 0755 "${binary_directory}/age" "${binary_directory}/age-keygen"

printf 'age v1.3.1 installed.\n'
