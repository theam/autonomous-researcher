from __future__ import annotations

import hashlib
import unittest

from scripts.console_contract import CHECKSUM_PATH, OPENAPI_PATH, contract_bytes


class ConsoleContractTest(unittest.TestCase):
    def test_committed_v2_openapi_matches_the_application(self) -> None:
        actual = OPENAPI_PATH.read_bytes()
        self.assertEqual(actual, contract_bytes())
        self.assertEqual(
            CHECKSUM_PATH.read_text(encoding="utf-8").strip(),
            hashlib.sha256(actual).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
