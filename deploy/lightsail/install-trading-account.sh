#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 || "$1" != "production" ]]; then
    printf 'Usage: %s production\n' "$0" >&2
    exit 2
fi

if [[ "${EUID}" -ne 0 ]]; then
    printf 'Production account installation must be run as root.\n' >&2
    exit 1
fi

image_ref="${CODEXPOLY_IMAGE_REF:-}"
if [[ ! "${image_ref}" =~ @sha256:[0-9a-f]{64}$ ]]; then
    printf 'CODEXPOLY_IMAGE_REF must be an immutable sha256 image reference.\n' >&2
    exit 1
fi

readonly secret_directory="/opt/codexpoly/secrets/prod"
readonly master_path="${secret_directory}/ACCOUNTS_MASTER_KEY"
readonly encrypted_path="${secret_directory}/TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED"

install -d -m 0700 -o root -g root "${secret_directory}"
if [[ -e "${master_path}" || -L "${master_path}" \
    || -e "${encrypted_path}" || -L "${encrypted_path}" ]]; then
    printf 'Trading account secrets already exist; rotation is refused.\n' >&2
    exit 1
fi

if ! /usr/bin/docker image inspect "${image_ref}" >/dev/null 2>&1; then
    printf 'The reviewed production image is unavailable.\n' >&2
    exit 1
fi

exec /usr/bin/docker run \
    --rm \
    --interactive \
    --tty \
    --read-only \
    --network none \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --pids-limit 64 \
    --memory 128m \
    --user 0:0 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --mount \
    "type=bind,src=${secret_directory},dst=/run/install-secrets" \
    "${image_ref}" \
    python -u -m scripts.install_single_account_secrets \
    --secret-directory /run/install-secrets
