from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
OFFSITE = ROOT / "deploy" / "lightsail" / "offsite"


class LightsailOffsiteBackupTests(unittest.TestCase):
    def test_vps_stage_is_atomic_validated_and_encrypted(self) -> None:
        script = (OFFSITE / "stage-offsite-backup.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("pg_restore --list", script)
        self.assertIn(".incomplete-", script)
        self.assertIn("--recipients-file", script)
        self.assertIn("*.age DATABASE_MANIFEST OFFSITE_MANIFEST", script)
        self.assertIn("COMPLETE", script)
        self.assertNotIn("system-config", script)
        self.assertNotIn("/secrets", script)

    def test_backup_user_is_forced_read_only_rrsync(self) -> None:
        installer = (OFFSITE / "install-offsite-access.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('restrict,command="/usr/bin/rrsync -ro %s"', installer)
        self.assertIn('readonly backup_user="nasbackup"', installer)
        self.assertNotIn("NOPASSWD", installer)

    def test_synology_pull_fails_closed_and_marks_verified(self) -> None:
        script = (
            OFFSITE / "synology" / "pull-codexpoly-backups.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("--partial", script)
        self.assertIn("--delay-updates", script)
        self.assertIn("BatchMode=yes", script)
        self.assertIn("StrictHostKeyChecking=yes", script)
        self.assertIn("HostKeyAlgorithms=ssh-ed25519", script)
        self.assertIn("UserKnownHostsFile=", script)
        self.assertIn('"${SHA256_BINARY}" --check SHA256SUMS', script)
        self.assertIn("VERIFIED", script)
        self.assertNotIn("--delete", script)

    def test_synology_age_installer_is_architecture_and_checksum_pinned(
        self,
    ) -> None:
        installer = (
            OFFSITE / "synology" / "install-age.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('"$(uname -m)" != "x86_64"', installer)
        self.assertIn("age-v1.3.1-linux-amd64", installer)
        self.assertIn(
            "bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377",
            installer,
        )
        self.assertIn("sha256sum", installer)

    def test_synology_bootstrap_uses_separate_targets(self) -> None:
        script = (
            OFFSITE / "synology" / "bootstrap-codexpoly-aws.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("aws-codexpoly-host-01-eu-west-1", script)
        self.assertIn("aws-codexpoly-host-02-eu-west-1", script)
        self.assertIn("known_hosts.host01", script)
        self.assertIn("known_hosts.host02", script)
        self.assertNotIn("vultr-polymarket-analytics-fra-1", script)

    def test_retention_is_scoped_to_completed_timestamp_directories(self) -> None:
        vps_script = (OFFSITE / "stage-offsite-backup.sh").read_text(
            encoding="utf-8"
        )
        nas_script = (
            OFFSITE / "synology" / "pull-codexpoly-backups.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('OFFSITE_RETENTION_DAYS:-60', vps_script)
        self.assertIn('[[ -f "${candidate}/COMPLETE" ]]', vps_script)
        self.assertIn('[[ "${candidate}" != "${newest_complete}" ]]', vps_script)
        self.assertIn('^[0-9]{8}T[0-9]{6}Z$', vps_script)

        self.assertIn('RETENTION_DAYS:-60', nas_script)
        self.assertIn('[ -f "${candidate}/COMPLETE" ]', nas_script)
        self.assertIn('[ -f "${candidate}/VERIFIED" ]', nas_script)
        self.assertIn('[ "${candidate}" != "${newest_verified}" ]', nas_script)
        self.assertNotIn("--delete", nas_script)


if __name__ == "__main__":
    unittest.main()
