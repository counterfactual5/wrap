"""The Skill's documentation must cover every draw the spec accepts.

`core/schema.py`'s DRAWS is what an author may write in a spec. The Skill
document is where an author looks up how — `captions` was legal and
implemented but absent from the documented list and had no parameter
description, so using it meant reading the renderer's source.

The first test keeps the two lists from drifting apart again: every draw in
the contract must appear in the Skill's layer list.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys_path = ROOT
import sys  # noqa: E402
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from core.schema import DRAWS  # noqa: E402

SKILL = os.path.join(ROOT, "skills", "code-driven-shot-pipeline", "SKILL.md")


def _skill_text():
    with open(SKILL) as f:
        return f.read()


class TestDrawDocumentation(unittest.TestCase):
    def test_00_every_draw_is_documented(self):
        """The contract and the documentation must not drift apart.

        A draw may be listed in the Layer Types enumeration (the primitives)
        or in the hero-scenes paragraph (the legacy hardcoded ones) — but it
        must be somewhere, or the author cannot look up how to use it."""
        text = _skill_text()
        for draw in DRAWS:
            with self.subTest(draw=draw):
                self.assertIn(draw, text,
                              f"draw {draw!r} is in the spec contract but the "
                              f"Skill never mentions it")

    def test_01_the_primitives_are_listed_in_the_layer_types(self):
        """The primitives the Layer Types line enumerates must be there."""
        text = _skill_text()
        m = re.search(r"\*\*`code`\*\* — (.+)", text)
        self.assertIsNotNone(m, "the Skill no longer lists the code layer types")
        listed = m.group(1)
        for draw in ("grid", "dots", "bar", "field", "path", "captions"):
            with self.subTest(draw=draw):
                self.assertIn(draw, listed,
                              f"primitive {draw!r} is missing from the Layer "
                              f"Types line")

    def test_02_captions_has_a_parameter_row(self):
        text = _skill_text()
        row = next((line for line in text.splitlines()
                    if line.startswith("| `captions`")), None)
        self.assertIsNotNone(row, "the Skill has no parameter row for captions")
        for param in ("items", "frame", "text", "hl", "size", "hlColor"):
            with self.subTest(param=param):
                self.assertIn(param, row,
                              f"captions' parameters do not mention {param!r}")

    def test_03_the_other_primitive_rows_are_kept(self):
        """Adding captions must not cost the author the other rows."""
        text = _skill_text()
        for channel in ("`anim`", "`field`", "`path`", "`vibe: false`",
                        "`plate: false`", "`color`"):
            with self.subTest(channel=channel):
                self.assertIn(f"| {channel} ", text)

    def test_04_the_documented_captions_params_match_the_renderer(self):
        """The documented names must be the ones the component reads."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "s5_doc", os.path.join(ROOT, "stages", "05_inspect.py"))
        # The component lives in the Remotion source; check the names there.
        with open(os.path.join(ROOT, "remotion", "layers.tsx")) as f:
            src = f.read()
        for param in ("items", "frame", "text", "hl", "size", "hlColor"):
            with self.subTest(param=param):
                self.assertIn(param, src,
                              f"the renderer does not use {param!r} — the "
                              f"documentation would be wrong")


if __name__ == "__main__":
    unittest.main()
