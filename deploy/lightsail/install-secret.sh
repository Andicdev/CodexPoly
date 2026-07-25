#!/usr/bin/env bash
set -euo pipefail

environment_name="${1:-}"
secret_name="${2:-}"
manifest_path="/opt/codexpoly/config/secret-manifest.json"

if [[ ! "${secret_name}" =~ ^[A-Z][A-Z0-9_]*$ ]]; then
    printf 'Usage: %s staging|production SECRET_NAME\n' "$0" >&2
    exit 2
fi

case "${environment_name}" in
    production)
        if [[ "${EUID}" -ne 0 ]]; then
            printf 'Production secret entry must be run as root.\n' >&2
            exit 1
        fi
        secret_directory="/opt/codexpoly/secrets/prod"
        ;;
    staging)
        if [[ "$(id -un)" != "codexdeploy" ]]; then
            printf 'Staging secret entry must be run as codexdeploy.\n' >&2
            exit 1
        fi
        secret_directory="${HOME}/.config/codexpoly/secrets/staging"
        ;;
    *)
        printf 'Usage: %s staging|production SECRET_NAME\n' "$0" >&2
        exit 2
        ;;
esac

if ! python3 - "${manifest_path}" "${environment_name}" "${secret_name}" <<'PY'
import json
import sys

manifest_path, environment_name, secret_name = sys.argv[1:]
with open(manifest_path, encoding="utf-8") as stream:
    manifest = json.load(stream)
services = manifest.get("environments", {}).get(environment_name, {})
allowed = {
    name
    for service_names in services.values()
    for name in service_names
}
raise SystemExit(0 if secret_name in allowed else 1)
PY
then
    printf 'Secret name is not allowed for %s.\n' "${environment_name}" >&2
    exit 1
fi

if [[ "${secret_name}" == "ACCOUNTS_MASTER_KEY" \
    || "${secret_name}" == "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED" ]]; then
    printf 'Trading account secrets must be generated and installed together.\n' >&2
    exit 1
fi

destination="${secret_directory}/${secret_name}"

install -d -m 0700 "${secret_directory}"
temporary_path="$(mktemp "${secret_directory}/.${secret_name}.XXXXXX")"
cleanup() {
    unset secret_value || true
    if [[ -n "${temporary_path:-}" && -e "${temporary_path}" ]]; then
        rm -f -- "${temporary_path}"
    fi
}
trap cleanup EXIT INT TERM

IFS= read -r -s -p "Enter ${secret_name}: " secret_value </dev/tty
printf '\n' >/dev/tty
if [[ -z "${secret_value}" ]]; then
    printf 'Empty values are not accepted.\n' >&2
    exit 1
fi

printf '%s' "${secret_value}" >"${temporary_path}"
unset secret_value
chmod 0444 "${temporary_path}"
if [[ "${environment_name}" == "production" ]]; then
    chown root:root "${temporary_path}"
fi
mv -f -- "${temporary_path}" "${destination}"
temporary_path=""
printf 'Installed %s for %s.\n' "${secret_name}" "${environment_name}"
