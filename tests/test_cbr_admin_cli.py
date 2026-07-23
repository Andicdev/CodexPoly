from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import cbr_trading.admin.cli as cli


def _event() -> dict:
    directions = (
        (
            "decrease",
            "Will the Bank of Russia decrease the key rate?",
            "a",
        ),
        (
            "no-change",
            "Will the Bank of Russia make no change to the key rate?",
            "b",
        ),
        (
            "increase",
            "Will the Bank of Russia increase the key rate?",
            "c",
        ),
    )
    return {
        "id": "event-1",
        "slug": "cbr-event",
        "title": "CBR event",
        "markets": [
            {
                "id": direction,
                "slug": direction,
                "question": question,
                "conditionId": "0x" + marker * 64,
                "active": True,
                "closed": False,
                "archived": False,
                "outcomes": '["Yes", "No"]',
            }
            for direction, question, marker in directions
        ],
    }


class AdminCliTests(unittest.TestCase):
    def test_default_mode_previews_without_creating_writer(self) -> None:
        output = io.StringIO()
        with (
            patch.object(cli, "_load_dotenv_if_available"),
            patch.object(cli, "GammaClient") as gamma_class,
            patch.object(cli, "SqlAlchemyRuleWriter") as writer_class,
            redirect_stdout(output),
        ):
            gamma_class.return_value.get_event_by_slug.return_value = (
                _event()
            )
            exit_code = cli.main(
                [
                    "--event-url",
                    "https://polymarket.com/event/cbr-event",
                    "--account-name",
                    "preview-account",
                ]
            )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "preview")
        self.assertEqual(len(payload["rules"]), 3)
        writer_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
