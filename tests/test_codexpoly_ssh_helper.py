from __future__ import annotations

import unittest
from pathlib import Path


_HELPER = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "codexpoly_ssh.ps1"
)


class CodexPolySshHelperTests(unittest.TestCase):
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
            "Get-Content -LiteralPath $resolvedSqlFile -Raw",
            text,
        )


if __name__ == "__main__":
    unittest.main()
