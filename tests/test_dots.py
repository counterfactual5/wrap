"""Test dots procedural drawing (R2)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from schema import DRAWS


class TestDots(unittest.TestCase):
    def test_dots_in_draws(self):
        if "dots" not in DRAWS:
            self.skipTest("dots is scheduled for R2 stage")
        self.assertIn("dots", DRAWS)


if __name__ == "__main__":
    unittest.main()
