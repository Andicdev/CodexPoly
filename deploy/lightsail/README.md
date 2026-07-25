# CodexPoly Lightsail deployment boundary

## Server roles

- Host: `codexpoly-host-01`
- Region: AWS Lightsail `eu-west-1` (Dublin)
- Static IPv4: `52.16.49.33`
- Deployment account: `codexdeploy`
- Local SSH helper: `scripts/codexpoly_ssh.ps1`
- Staging workspace: `/opt/codexpoly/staging`
- Production workspace: `/opt/codexpoly/production`
- Secret store: `/opt/codexpoly/secrets`
- Name-only manifest: `/opt/codexpoly/config/secret-manifest.json`

`codexdeploy` is not a member of the host Docker group and has no general
`sudo` access. Its only production privilege is the exact root-owned
`/usr/local/sbin/codexpoly-production-migrate` command. The host Docker daemon,
production deployments, secrets, backups, and every other root operation
remain under the infrastructure administrator's control.

## Secret model

Each secret is stored as one file:

```text
/home/codexdeploy/.config/codexpoly/secrets/staging/<SECRET_NAME>
/opt/codexpoly/secrets/prod/<SECRET_NAME>
```

Production files must be owned by `root:root` with mode `0444`, inside a
`root:root` directory with mode `0700`. The root-only parent prevents host
users from reaching the files, while the read-only file mode lets a non-root
application user read a Compose file-secret after it is mounted. Secret values
must be entered by a human directly on the server and must never be pasted into
a Codex chat, shell command argument, repository file, log, screenshot, or
Docker image.

The administrator can install one value with a no-echo terminal prompt:

```bash
sudo /opt/codexpoly/config/install-secret.sh \
  production SECRET_NAME
```

This command is intentionally a human-only step. Staging uses the same script
without `sudo`, while logged in as `codexdeploy`. Staging values must be
disposable and must never be reused in production because staging code can
technically read every secret mounted into it.

Docker Compose grants each service only the names listed in
`secret-manifest.json` and mounts them as:

```text
/run/secrets/<SECRET_NAME>
```

Application code should resolve `<SECRET_NAME>_FILE` first, then
`/run/secrets/<SECRET_NAME>`, and use the ordinary environment variable only
as a local-development fallback. It must never log the value, its length, or a
derived hash.

Any application process that is granted a secret can technically read that
secret. "Use by name" prevents accidental exposure in development chats and
deployment configuration; it cannot make a value unreadable to arbitrary code
that receives it. For this reason, only reviewed production images are promoted
by the infrastructure administrator, and `codexdeploy` cannot control the
production Docker daemon.

The presence checker reports names only:

```bash
python /opt/codexpoly/config/check_server_secret_files.py \
  --environment production \
  --service cbr-worker
```

For staging, `codexdeploy` supplies its own non-production root:

```bash
python /opt/codexpoly/config/check_server_secret_files.py \
  --secret-root /home/codexdeploy/.config/codexpoly/secrets \
  --environment staging \
  --service cbr-worker
```

`ACCOUNTS_MASTER_KEY` must not be replaced unless encrypted trading-account
records are migrated in the same operation.

For the isolated production account, do not install
`ACCOUNTS_MASTER_KEY` or
`TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED` separately. The reviewed image
generates and installs the pair through:

```bash
sudo --preserve-env=CODEXPOLY_IMAGE_REF \
  /opt/codexpoly/config/install-trading-account.sh production
```

The installer refuses replacement. Staging does not receive either trading
secret. Worker composition and promotion are documented in
`deploy/lightsail/workers/README.md`.

## Database boundary

PostgreSQL should be reachable by application containers only over an internal
Compose network, using the non-public hostname `postgres:5432`. Do not publish
port `5432` in Lightsail or bind it to the public interface.

Internal workers receive only `DATABASE_APP_PASSWORD`; the non-secret
`DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, and `DATABASE_USER` values
are used to construct the URL at runtime. PostgreSQL receives that application
password plus a separate `POSTGRES_PASSWORD`. Only the database container
receives `POSTGRES_PASSWORD`, so neither ordinary workers nor migration tasks
receive schema-administrator credentials.

`DATABASE_URL_SERVER_EXT` remains an optional single secret for a managed
external database, where provider-specific host, TLS, and query parameters make
a complete URL more practical. It is not mounted unless a service truly needs
it.

PostgreSQL is not bound to a host port. Infrastructure administration uses the
root-controlled database container. The trusted development task submits
complete migrations through fixed stdin-only runners:

```bash
/opt/codexpoly/config/codexpoly-staging-migrate < migration.sql
sudo /usr/local/sbin/codexpoly-production-migrate < migration.sql
```

The production runner is the only allowed sudo command. It runs SQL as
`codexpoly_admin`, stops on the first error, and never displays raw PostgreSQL
output. It does not expose `POSTGRES_PASSWORD`. The SQL file or migration
framework controls its own transaction. Production secret changes and restores
remain in this infrastructure task.

The installed PostgreSQL layout, application connection settings, migration
boundary, and backup locations are documented in
`deploy/lightsail/database/README.md`.

## Earnings worker boundary

The earnings source and resolution executor are separate private services on
the database network:

- `earnings-worker` receives `DATABASE_APP_PASSWORD` and `SEC_API_KEY`;
- the base `resolution-worker` receives only `DATABASE_APP_PASSWORD` and runs
  in shadow mode;
- only the explicit production trading overlay grants the resolution worker
  the two trading account secrets.

No worker publishes a port. Production account metadata selects the single
account `abccbaq` with venue `polymarket_clob` and signature type `2`. It is
stored in the additive `trading_account_metadata` table. There is no
production legacy `trading_accounts` row for this account, and no private key
is stored in the metadata table.

See `deploy/lightsail/workers/README.md` and the Compose sources in the same
directory.

## Handoff rules for the development task

The development task may:

- connect as `codexdeploy`;
- use
  `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/codexpoly_ssh.ps1`
  from the repository;
- upload code and immutable release artifacts to
  `/opt/codexpoly/staging/releases`;
- run staging services after the rootless staging runtime is enabled;
- refer to secret names from `secret-manifest.json`;
- apply staging migrations through the staging runner;
- apply committed production migrations through the production runner after a
  successful staging run.

It must not:

- request or display secret values;
- request any additional `sudo` access or membership in the host Docker group;
- open public database or application ports;
- modify `/opt/codexpoly/production` or `/opt/codexpoly/secrets`;
- use any sudo command except the exact production migration runner;
- rotate `ACCOUNTS_MASTER_KEY`.
