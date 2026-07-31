# Encrypted Synology offsite backups

This layer transfers production PostgreSQL dumps only. Application source is
recovered from Git, and deployment secrets are re-entered manually after a
disaster. Secret files, staging state, live Docker volumes, logs, build trees,
release archives, and Docker images are deliberately excluded.

Each VPS validates the newest same-run production dumps with `pg_restore
--list`, encrypts them with the target-specific Synology `age` recipient, and
atomically publishes a read-only timestamp directory under:

```text
/var/backups/codexpoly/offsite
```

The age private identity exists only on Synology. The VPS user `nasbackup` has
one restricted SSH key forced through:

```text
/usr/bin/rrsync -ro /var/backups/codexpoly/offsite
```

The NAS stores the two targets separately:

```text
/volume1/Backups/VPS/aws-codexpoly-host-01-eu-west-1
/volume1/Backups/VPS/aws-codexpoly-host-02-eu-west-1
```

After rsync, Synology verifies `SHA256SUMS` and creates `VERIFIED`. No automated
deletion happens before a successful transfer and verification. VPS staging and
Synology both retain 60 days of completed timestamp directories and always keep
the newest completed copy even when it is older than the retention window. The
existing Vultr configuration is not reused or modified.

Suggested Synology Task Scheduler times are 05:10 local for host01 and 05:30
local for host02. Both run as root and invoke:

```text
/bin/sh /volume1/Backups/VPS/codexpoly-aws-setup/pull-codexpoly-backups.sh TARGET_NAME
```

The existing Vultr task remains at 06:00 local.
