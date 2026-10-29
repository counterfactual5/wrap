"""Test dots procedural drawing."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from schema import DRAWS


class TestDots(unittest.TestCase):
    def test_dots_in_draws(self):
        self.assertIn("dots", DRAWS, "dots should be in DRAWS")


if __name__ == "__main__":
    unittest.main()
