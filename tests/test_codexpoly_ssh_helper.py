from __future__ import annotations

import unittest
from pathlib import Path


_HELPER = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "codexpoly_ssh.ps1"
)


class CodexPolySshHelperTests(unittest.TestCase):
    def test_target_selection_preserves_primary_default(self) -> None:
        text = _HELPER.read_text(encoding="utf-8")

        self.assertIn('[ValidateSet("host01", "host02")]', text)
        self.assertIn('[string]$Target = "host01"', text)
        self.assertIn('host01 = "52.16.49.33"', text)
        self.assertIn('host02 = "54.73.200.228"', text)
        self.assertIn('$sshArguments += "codexdeploy@$targetHost"', text)

    def test_stdin_mode_is_restricted_to_sql_files(self) -> None:
        text = _HELPER.read_text(encoding="utf-8")

        self.assertIn("[string]$StdinSqlFile", text)
        self.assertIn(
            '[IO.Path]::GetExtension($resolvedSqlFile) -ne ".sql"',
            text,
        )
        self.assertIn(
            '"A remote migration runner command is required."',
            text,
        )
        self.assertIn(
            "Position = 0",
            text,
        )
        self.assertIn(
            "ValueFromRemainingArguments = $true",
            text,
        )
        self.assertIn(
            "Get-Content -LiteralPath $resolvedSqlFile -Raw",
            text,
        )

    def test_interactive_mode_allocates_a_remote_tty(self) -> None:
        text = _HELPER.read_text(encoding="utf-8")

        self.assertIn("[switch]$Interactive", text)
        self.assertIn('$sshArguments += "-tt"', text)
        self.assertIn(
            "Interactive mode cannot be combined with StdinSqlFile.",
            text,
        )


if __name__ == "__main__":
    unittest.main()
