from __future__ import annotations

import unittest

from scripts.sanitize_runtime_logs import sanitized_matching_lines


class SanitizeRuntimeLogsTests(unittest.TestCase):
    def test_redacts_before_selecting_health_line(self) -> None:
        token = "123456789:" + "A" * 35
        lines = sanitized_matching_lines(
            (
                f"Profile lifecycle ready token={token}\n"
                "unrelated private diagnostic\n"
            ),
            markers=("Profile lifecycle ready",),
        )

        self.assertEqual(len(lines), 1)
        self.assertIn("Profile lifecycle ready", lines[0])
        self.assertNotIn(token, lines[0])
        self.assertNotIn("unrelated", lines[0])

    def test_requires_explicit_marker(self) -> None:
        with self.assertRaisesRegex(ValueError, "marker"):
            sanitized_matching_lines("anything", markers=())


if __name__ == "__main__":
    unittest.main()
