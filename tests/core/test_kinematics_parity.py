"""Cross-language parity between the Python rig validators and the Remotion renderer.

`remotion/kinematics.ts` is the authoritative implementation of the animation
math: the Python rig validators (combat / blocking / stagecraft) gate the pixels
Remotion draws, so both sides must land on the same number for the same spec and
the same frame. Two layers of evidence keep that contract honest:

* `EASE_REFERENCE` is the renderer's own ease table, captured from `applyEase`
  in remotion/kinematics.ts (the seven curves of `core.spec.constants.ANIM_EASES`).
  It pins the Python curves without needing a runtime.
* `_ts_run` executes the *shipped* TypeScript module under node (node strips the
  types natively) and compares frame by frame, so the Python side is checked
  against the renderer itself rather than against a transcription of it. No
  temporary files are involved: the driver travels in argv, the payload on stdin.
"""
import json
import os
import shutil
import subprocess
import unittest

from core.rig.kinematics import apply_ease, eval_channel, solve_spring_damper_track
from core.spec.constants import ANIM_EASES

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KINEMATICS_TS = os.path.join(ROOT, "remotion", "kinematics.ts")

# applyEase(t, ease) in remotion/kinematics.ts, sampled per curve.
EASE_REFERENCE = {
    "linear": [(0, 0.0), (0.1, 0.1), (0.25, 0.25), (0.3, 0.3), (0.5, 0.5),
                (0.75, 0.75), (0.9, 0.9), (1.0, 1.0)],
    "in": [(0, 0.0), (0.1, 0.010000000000000002), (0.25, 0.0625), (0.3, 0.09),
           (0.5, 0.25), (0.75, 0.5625), (0.9, 0.81), (1.0, 1.0)],
    "out": [(0, 0.0), (0.1, 0.18999999999999995), (0.25, 0.4375), (0.3, 0.51),
            (0.5, 0.75), (0.75, 0.9375), (0.9, 0.99), (1.0, 1.0)],
    "inout": [(0, 0.0), (0.1, 0.020000000000000004), (0.25, 0.125), (0.3, 0.18),
              (0.5, 0.5), (0.75, 0.875), (0.9, 0.98), (1.0, 1.0)],
    "snap": [(0, 0.0), (0.1, 0.3439), (0.25, 0.68359375), (0.3, 0.7599),
             (0.5, 0.9375), (0.75, 0.99609375), (0.9, 0.9999), (1.0, 1.0)],
    "overshoot": [(0, 2.220446049250313e-16), (0.1, 0.40882797999999987),
                  (0.25, 0.8174096875000002), (0.3, 0.9071322600000001),
                  (0.5, 1.0876975), (0.75, 1.0641365625), (0.9, 1.01431422),
                  (1.0, 1.0)],
    "step": [(0, 0.0), (0.1, 0.0), (0.25, 0.0), (0.3, 0.0), (0.5, 0.0),
             (0.75, 0.0), (0.9, 0.0), (1.0, 1.0)],
}

# Driver evaluated by node: it imports the shipped renderer and answers with
# the values that renderer produces.
_TS_DRIVER = r"""
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const mod = await import(pathToFileURL(process.env.WRAP_TS_KINEMATICS).href);
const payload = JSON.parse(readFileSync(0, 'utf8'));
const results = payload.map(req => {
  if (req.kind === 'channel') {
    return {values: req.frames.map(f => mod.channelValue(req.kfs, f, req.fallback))};
  }
  const map = {};
  for (const l of req.layers) map[l.id] = l;
  try {
    return {frame: req.frame, value: mod.evalLayerTransform(req.layer, req.frame, req.fps, map)};
  } catch (e) {
    return {frame: req.frame, error: String(e && e.message ? e.message : e)};
  }
});
process.stdout.write(JSON.stringify(results));
"""


def _ts_run(payload):
    """Evaluate `payload` with the shipped Remotion kinematics module."""
    node = shutil.which("node")
    if node is None:
        raise unittest.SkipTest("node is required to run the renderer reference")
    env = dict(os.environ, WRAP_TS_KINEMATICS=KINEMATICS_TS)
    proc = subprocess.run(
        [node, "--disable-warning=MODULE_TYPELESS_PACKAGE_JSON", "--input-type=module",
         "-e", _TS_DRIVER],
        input=json.dumps(payload), cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError(f"renderer reference run failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


def _channel_cases():
    """Keyframe tracks covering every ease, several frame spans and the edges."""
    cases = []
    for ease in sorted(ANIM_EASES):
        # one segment; the ease lives on the segment's *last* keyframe
        cases.append(([[0, 0], [10, 100, ease]], list(range(-2, 13)), 0.0))
        # an ease on the segment's *first* keyframe must not shape the segment
        cases.append(([[0, 0, ease], [10, 100]], list(range(0, 11)), 0.0))
        # a following segment takes its ease from its own last keyframe
        cases.append(([[0, 0], [10, 100, ease], [20, -40]], list(range(0, 21)), 0.0))
    # uneven spans, a two-element keyframe (no ease -> linear), fractional values
    cases.append(([[0, 0], [3, 100, "snap"], [4, 120], [17, -30.5, "overshoot"]],
                  list(range(0, 19)), 0.0))
    cases.append(([[0, 0], [10, 100]], [0, 1, 5, 10, 11], 0.0))
    cases.append(([[5, 12.5], [15, -7.25]], [0, 5, 10, 15, 20], 0.0))
    # a zero-length segment between two different frames
    cases.append(([[0, 0], [0, 100, "in"], [10, 200]], [0, 1, 5, 10], 0.0))
    # an empty track falls back on both sides
    cases.append(([], [0, 5], 0.25))
    return cases


class EaseCurveTests(unittest.TestCase):
    """The Python curves are the renderer's curves."""

    def test_ease_reference_covers_every_declared_ease(self):
        self.assertEqual(sorted(EASE_REFERENCE), sorted(ANIM_EASES))

    def test_apply_ease_matches_the_renderer_reference(self):
        for ease, samples in EASE_REFERENCE.items():
            for t, expected in samples:
                with self.subTest(ease=ease, t=t):
                    self.assertAlmostEqual(apply_ease(t, ease), expected, delta=1e-12)

    def test_apply_ease_rejects_an_undeclared_ease(self):
        with self.assertRaises(ValueError):
            apply_ease(0.5, "bounce")


class EvalChannelParityTests(unittest.TestCase):
    """eval_channel() must land on the same number as the renderer's channelValue()."""

    def test_eval_channel_matches_the_renderer_frame_by_frame(self):
        cases = _channel_cases()
        payload = [{"kind": "channel", "kfs": kfs, "frames": frames, "fallback": fallback}
                   for kfs, frames, fallback in cases]
        for (kfs, frames, fallback), rendered in zip(cases, _ts_run(payload)):
            for frame, ts_value in zip(frames, rendered["values"]):
                with self.subTest(kfs=kfs, frame=frame):
                    self.assertAlmostEqual(
                        eval_channel(kfs, frame, fallback), ts_value, delta=1e-9,
                        msg=(f"keyframes {kfs!r} at frame {frame}: python "
                             f"{eval_channel(kfs, frame, fallback)!r} != renderer {ts_value!r}"))

    def test_eased_track_is_not_linear(self):
        """The regression this parity guards: the validator used to ignore ease."""
        kfs = [[0, 0], [10, 100, "in"]]
        self.assertAlmostEqual(eval_channel(kfs, 2), 4.0, delta=1e-9)
        self.assertAlmostEqual(eval_channel(kfs, 5), 25.0, delta=1e-9)
        self.assertAlmostEqual(eval_channel(kfs, 8), 64.0, delta=1e-9)
        self.assertAlmostEqual(eval_channel(kfs, 10), 100.0, delta=1e-9)


class SpringParityTests(unittest.TestCase):
    """The renderer rejects an undeclared spring; the offline baker matches it."""

    @staticmethod
    def _layers(spring):
        parent = {"id": "scene", "type": "component", "component": "Scene",
                  "rect": [0, 0, 10, 10], "z": 0, "anim": {"x": [[0, 0], [10, 100]]}}
        child = {"id": "child", "type": "image", "asset": "a", "rect": [0, 0, 10, 10],
                 "z": 1, "parent": "scene", "spring": spring}
        return parent, child

    def test_renderer_rejects_a_null_spring_field(self):
        base = {"omega": 18, "zeta": 0.25, "coupling": 0.45, "maxAccel": 4500,
                "channel": "x", "driverChannel": "x"}
        for field in sorted(base):
            with self.subTest(field=field):
                spring = dict(base, **{field: None})
                parent, child = self._layers(spring)
                result = _ts_run([{"kind": "spring", "layers": [parent, child],
                                   "layer": child, "frame": 10, "fps": 30}])[0]
                self.assertIn("error", result,
                              msg=f"spring.{field}=null must be rejected, not silently defaulted")
                self.assertIn("no defaults", result["error"])

    def test_renderer_rejects_a_missing_spring_field(self):
        base = {"omega": 18, "zeta": 0.25, "coupling": 0.45, "maxAccel": 4500,
                "channel": "x", "driverChannel": "x"}
        for field in sorted(base):
            with self.subTest(field=field):
                spring = {k: v for k, v in base.items() if k != field}
                parent, child = self._layers(spring)
                result = _ts_run([{"kind": "spring", "layers": [parent, child],
                                   "layer": child, "frame": 10, "fps": 30}])[0]
                self.assertIn("error", result)

    def test_renderer_accepts_a_fully_declared_spring(self):
        spring = {"omega": 18, "zeta": 0.25, "coupling": 0.45, "maxAccel": 4500,
                  "channel": "x", "driverChannel": "x"}
        parent, child = self._layers(spring)
        result = _ts_run([{"kind": "spring", "layers": [parent, child],
                           "layer": child, "frame": 10, "fps": 30}])[0]
        self.assertNotIn("error", result)
        self.assertNotEqual(result["value"]["x"], 0.0)

    def test_renderer_source_carries_an_explicit_null_check(self):
        """Guard the fix even where node is unavailable."""
        with open(KINEMATICS_TS, "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("=== null", source,
                      "the spring guard must reject null, not only undefined")
        self.assertNotIn("spring?.channel ??", source,
                         "a null channel must not collapse into a default channel")

    def test_offline_spring_bake_matches_the_live_renderer_spring(self):
        """The offline baker (core.rig) and the live spring (remotion) solve one ODE.

        With no rest track the two must agree frame for frame; the bake quantizes
        its output to two decimals, so the tolerated difference is that quantum.
        """
        driver_kfs = [[0, 0], [10, 0], [16, 60, "snap"], [60, 200, "in"]]
        fps, omega, zeta, coupling, max_accel = 30, 20.0, 0.22, 0.45, 4500.0
        total_frames = 60
        track = solve_spring_damper_track(driver_kfs, total_frames, fps, omega, zeta,
                                          coupling, max_accel=max_accel, step_frames=1)
        baked = {f: v for f, v in track}
        parent = {"id": "scene", "type": "component", "component": "Scene",
                  "rect": [0, 0, 10, 10], "z": 0, "anim": {"x": driver_kfs}}
        child = {"id": "child", "type": "image", "asset": "a", "rect": [0, 0, 10, 10],
                 "z": 1, "parent": "scene",
                 "spring": {"omega": omega, "zeta": zeta, "coupling": coupling,
                            "maxAccel": max_accel, "channel": "x", "driverChannel": "x"}}
        payload = [{"kind": "spring", "layers": [parent, child], "layer": child,
                    "frame": f, "fps": fps} for f in range(total_frames)]
        for rendered in _ts_run(payload):
            frame = rendered["frame"]
            with self.subTest(frame=frame):
                self.assertAlmostEqual(baked[frame], rendered["value"]["x"], delta=0.005 + 1e-9)


class UnroundedVerdictTests(unittest.TestCase):
    """Verdicts compare the transform as computed, never a rounded report value.

    The renderer quantizes the drawn transform to two decimals (Shot.tsx
    `toFixed(2)`); the validators compare the true value, so a margin that only
    clears the threshold after rounding still has to fail.
    """

    def test_combat_compares_the_unrounded_gap(self):
        from core.rig.verification.combat import verify_combat_contact

        # The tip stops 40.04px short of a hitbox that starts at x=600.
        spec = {
            "id": "shot", "fps": 30, "durationInFrames": 11,
            "tracks": {"events": [{"frame": 10, "kind": "contact"}]},
            "combat": {"attacker": "hero", "weapon": "staff", "target": "enemy",
                       "tolerance": 40, "tipOffset": [0, 0], "refWidth": 100},
            "layers": [
                {"id": "hero", "rect": [0, 0, 100, 200], "anim": {"x": [[0, 0], [10, 559.96]]}},
                {"id": "staff", "rect": [0, 0, 100, 100], "pivot": [0, 0],
                 "anim": {"rotate": [[0, 0], [10, 0]]}},
                {"id": "enemy", "rect": [600, 0, 200, 300], "anim": {"x": [[0, 0], [10, 0]]}},
            ],
        }
        result = verify_combat_contact(spec)
        self.assertFalse(result["passed"])
        self.assertEqual(result["details"][0]["status"], "WHIFFING_SHORT")
        self.assertEqual(result["details"][0]["gap_px"], 40.0)  # reported rounded

    def test_blocking_compares_the_unrounded_overlap(self):
        from core.rig.verification.blocking import verify_stage_blocking

        spec = {
            "id": "shot", "fps": 30, "durationInFrames": 5,
            "layers": [
                {"id": "left", "type": "component", "role": "humanoid",
                 "rect": [0, 0, 100, 200], "blockCore": [0.0, 1.0]},
                {"id": "right", "type": "component", "role": "humanoid",
                 "rect": [87.96, 0, 100, 200], "blockCore": [0.0, 1.0]},
            ],
        }
        result = verify_stage_blocking(spec, max_overlap_px=12.0)
        self.assertFalse(result["passed"])
        self.assertEqual(result["pairs"][0]["status"], "OVERLAP")
        self.assertEqual(result["pairs"][0]["max_overlap_px"], 12.0)  # reported rounded


class EasedVerdictTests(unittest.TestCase):
    """The validators must measure the world the renderer draws — eased ones.

    Both cases below flip their verdict when the ease is ignored, which is how
    the validator used to disagree with the rendered frame.
    """

    def test_combat_judges_the_eased_position_of_the_attacker(self):
        from core.rig.verification.combat import verify_combat_contact

        # "in" easing puts the tip at 25px at frame 5 (linear would say 50px).
        # The hitbox starts at x=40, so the eased tip misses it by 15px while a
        # linear tip would have landed inside the target.
        spec = {
            "id": "shot", "fps": 30, "durationInFrames": 11,
            "tracks": {"events": [{"frame": 5, "kind": "contact"}]},
            "combat": {"attacker": "hero", "weapon": "staff", "target": "enemy",
                       "tolerance": 10, "tipOffset": [0, 0], "refWidth": 100},
            "layers": [
                {"id": "hero", "rect": [0, 0, 100, 200],
                 "anim": {"x": [[0, 0], [10, 100, "in"]]}},
                {"id": "staff", "rect": [0, 0, 100, 100], "pivot": [0, 0],
                 "anim": {"rotate": [[0, 0], [10, 0]]}},
                {"id": "enemy", "rect": [40, 0, 200, 300], "anim": {"x": [[0, 0], [10, 0]]}},
            ],
        }
        result = verify_combat_contact(spec)
        self.assertEqual(result["details"][0]["status"], "WHIFFING_SHORT")
        self.assertFalse(result["passed"])

    def test_blocking_judges_the_eased_position_of_the_character(self):
        from core.rig.verification.blocking import verify_stage_blocking

        # The right character eases left by 100px; "in" easing crosses the
        # overlap threshold on frame 4, a linear move would cross it on frame 2.
        spec = {
            "id": "shot", "fps": 30, "durationInFrames": 11,
            "layers": [
                {"id": "left", "type": "component", "role": "humanoid",
                 "rect": [0, 0, 100, 200], "blockCore": [0.0, 1.0]},
                {"id": "right", "type": "component", "role": "humanoid",
                 "rect": [70, 0, 100, 200], "blockCore": [0.0, 1.0],
                 "anim": {"x": [[0, 0], [10, -100, "in"]]}},
            ],
        }
        result = verify_stage_blocking(spec, max_overlap_px=40.0)
        self.assertFalse(result["passed"])
        self.assertIn("frames 4..", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
