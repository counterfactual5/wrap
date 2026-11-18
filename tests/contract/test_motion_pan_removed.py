"""motion.pan is a REMOVED word — the renderer must not apply it either.

The contract side is loud: `core/spec/layers.py` refuses `motion.pan` with
"migration required: motion.pan removed; use anim.x". The renderer side was
not. `remotion/Shot.tsx` read `layer.motion.pan` and interpolated it into a
`translateX`, so a spec the contract refuses still MOVED on screen — the
"never render a removed word implicitly" rule, broken in the one place the
contract tests cannot see: they compare layer TYPES, never fields.

This file pins the field-level agreement:

  * the renderer must not read `motion.pan` (source scan over remotion/,
    with a counter-proof that the scan would catch a reintroduction);
  * the contract must keep refusing it loudly;
  * `motion.zoom` — the surviving capability of the same object — must stay
    on both sides.

The renderer source list has ONE definition (tests/contract/agreement.py
owns it), so a new renderer file cannot slip past this check by not being
scanned.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from tests.contract.agreement import _renderer_sources, strip_comments  # noqa: E402

from core.spec.shot import validate  # noqa: E402

# The removed word as an identifier. Comments are stripped before the scan,
# so a note mentioning the word cannot keep the renderer honest.
_PAN_WORD = re.compile(r"\bpan\b")

# motion.zoom is alive: the renderer must keep reading it.
_ZOOM_READ = re.compile(r"motion\s*\??\.\s*zoom")


def pan_reads(src):
    """Every 'pan' identifier in `src`, comments stripped."""
    return [m.group(0) for m in _PAN_WORD.finditer(strip_comments(src))]


def _spec(layer):
    return {
        "id": "motion-pan-probe",
        "canvas": {"w": 1080, "h": 1920},
        "fps": 30,
        "durationInFrames": 60,
        "layers": [layer],
        "gates": [{"id": "m", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.15}],
    }


def _ai_layer(**extra):
    layer = {"id": "l", "type": "ai", "asset": "a", "keyColor": "#070512",
             "blend": "normal", "rect": [0, 0, 1080, 1920], "z": 0}
    layer.update(extra)
    return layer


class TestTheRendererDoesNotReadTheRemovedWord(unittest.TestCase):
    def test_00_no_renderer_file_reads_motion_pan(self):
        """The hole this file closes: the contract refuses motion.pan, so
        the renderer must not apply it. A read would move the picture on a
        spec the contract already rejects."""
        for path in _renderer_sources():
            with open(path, encoding="utf-8") as f:
                hits = pan_reads(f.read())
            self.assertEqual(hits, [],
                             f"{os.path.relpath(path, ROOT)} uses the removed "
                             f"word 'pan' — motion.pan was removed (use "
                             f"anim.x); the renderer must not apply it")

    def test_01_the_scan_would_catch_a_reintroduction(self):
        """The counter-proof: a check that cannot fail is decoration."""
        crafted = ("const pan = layer.motion?.pan ?? [0, 0];\n"
                   "const x = interpolate(frame, [0, end], pan);\n")
        self.assertTrue(pan_reads(crafted),
                        "the scan no longer sees a motion.pan read")
        # The shape the fix took must read as clean.
        self.assertEqual(pan_reads("const zoom = layer.motion?.zoom ?? [1, 1];"), [])
        # A comment is not a read.
        self.assertEqual(pan_reads("// motion.pan was removed; use anim.x\n"), [])


class TestTheContractStillRefusesItLoudly(unittest.TestCase):
    def test_00_pan_is_a_migration_error(self):
        errs = validate(_spec(_ai_layer(motion={"type": "geometric", "pan": [0, 40]})))
        self.assertTrue(
            any("migration required" in e and "pan" in e for e in errs),
            f"the contract must refuse motion.pan loudly: {errs}")

    def test_01_the_renderer_and_the_contract_agree_on_pan(self):
        """The agreement itself: what the contract refuses, the renderer
        cannot apply. Both halves are checked here — the contract refuses
        (above), the renderer does not read it (the source scan)."""
        refused = validate(_spec(_ai_layer(motion={"type": "geometric", "pan": [0, 40]})))
        self.assertTrue(any("migration required" in e for e in refused))
        rendered = []
        for path in _renderer_sources():
            with open(path, encoding="utf-8") as f:
                rendered.extend(pan_reads(f.read()))
        self.assertEqual(rendered, [])


class TestZoomIsStillALiveCapability(unittest.TestCase):
    """motion.zoom is NOT removed: the contract accepts it for prepared
    media, and the renderer interpolates it. Removing the pan hole must not
    take the zoom with it."""

    def test_00_the_contract_accepts_zoom_on_prepared_media(self):
        errs = validate(_spec(_ai_layer(motion={"type": "geometric", "zoom": [1.0, 1.2]})))
        self.assertEqual(errs, [])

    def test_01_the_renderer_still_reads_motion_zoom(self):
        found = []
        for path in _renderer_sources():
            with open(path, encoding="utf-8") as f:
                if _ZOOM_READ.search(strip_comments(f.read())):
                    found.append(os.path.relpath(path, ROOT))
        self.assertTrue(found,
                        "the renderer no longer reads motion.zoom — zoom is a "
                        "live capability and must keep working")


if __name__ == "__main__":
    unittest.main()
