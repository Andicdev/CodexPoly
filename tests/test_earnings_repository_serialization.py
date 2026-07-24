from __future__ import annotations

import json
import unittest

from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.repository import (
    _json_dumps,
    _json_mapping,
)


class EarningsRepositorySerializationTests(unittest.TestCase):
    def test_immutable_rule_policies_remain_json_objects(self) -> None:
        rule = nvts_q2_2026_shadow_rule()

        encoded = _json_dumps(rule.source_policy)
        decoded = json.loads(encoded)

        self.assertIsInstance(decoded, dict)
        self.assertEqual(
            decoded["sec"]["document_type"],
            "EX-99.1",
        )
        self.assertEqual(_json_mapping(encoded), decoded)

    def test_unsupported_object_is_not_silently_stringified(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "unsupported JSON value type",
        ):
            _json_dumps(object())


if __name__ == "__main__":
    unittest.main()
