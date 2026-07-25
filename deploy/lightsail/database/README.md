# CodexPoly PostgreSQL on Lightsail

## Installed databases

Both environments run PostgreSQL 18.4 in separate Docker daemons, networks,
volumes, and secret stores.

| Environment | Runtime | Compose file on server | Docker network | Volume |
| --- | --- | --- | --- | --- |
| staging | `codexdeploy` rootless Docker | `/opt/codexpoly/staging/apps/database/compose.yml` | `codexpoly-staging-backend` | `codexpoly_staging_postgres_data` |
| production | system Docker | `/opt/codexpoly/production/apps/database/compose.yml` | `codexpoly-production-backend` | `codexpoly_production_postgres_data` |

Neither Compose file publishes a host port. PostgreSQL is available only as
`postgres:5432` to containers that explicitly join the matching internal
network.

## Database and roles

- Database: `codexpoly`
- Administrator and migration role: `codexpoly_admin`
- Runtime role: `codexpoly_app`
- Application tables: intentionally not created by infrastructure setup

`codexpoly_app` is not a superuser and cannot create databases or roles.
Tables created by `codexpoly_admin` inherit default CRUD and sequence
permissions for `codexpoly_app`.

Application containers use:

```text
PRIMARY_DB_TARGET=server_int
DATABASE_HOST=postgres
DATABASE_PORT=5432
DATABASE_NAME=codexpoly
DATABASE_USER=codexpoly_app
```

They receive only the `DATABASE_APP_PASSWORD` file-secret. CodexPoly constructs
the internal SQLAlchemy URL at runtime; a complete credential-bearing URL does
not need to appear in Compose or environment configuration.

## Migration boundary

Development tasks may write and apply transactional SQL migrations to both
environments through fixed stdin-only commands:

```bash
# staging
/opt/codexpoly/config/codexpoly-staging-migrate < migration.sql

# production
sudo /usr/local/sbin/codexpoly-production-migrate < migration.sql
```

The production sudo rule permits only the second wrapper. It does not grant an
interactive root shell, arbitrary sudo commands, the system Docker socket, or
the database administrator password. Both wrappers execute SQL as
`codexpoly_admin`, stop on the first error, and suppress raw PostgreSQL output
so query results or error details cannot leak data.

The wrapper rejects empty SQL, input larger than 5 MiB, and psql meta-commands.
It intentionally does not restrict PostgreSQL DDL or DML: the development task
is trusted to perform complete database migrations. A migration file or its
framework is responsible for adding `BEGIN` and `COMMIT` when atomic execution
is required; non-transactional PostgreSQL operations are also supported.

This is a database privilege, not a read-only deployment permission. A person
allowed to submit migrations can intentionally change or delete application
schema, roles, and data in `codexpoly`. It is available to the trusted
development task and should be used only after staging succeeds and the
migration is committed.

## Backups

Production logical backups run daily through
`codexpoly-postgres-backup.timer` and are retained for 14 days:

```text
/opt/codexpoly/backups/postgres/production
```

The initial production backup was created during installation. Lightsail disk
snapshots remain a separate disaster-recovery layer.

Staging backups can be created manually by `codexdeploy`:

```bash
/opt/codexpoly/config/backup-postgres.sh staging
```

They are written to:

```text
/opt/codexpoly/staging/backups/postgres
```

Do not inspect backup contents in ordinary Codex tasks. Restore tests and
production restores belong to the infrastructure task.
