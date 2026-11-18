"""No implicit default for the shot id.

`id` names a shot's asset namespace: `build/frames/{id}/`, `build/{id}.mp4`,
`public/prepared/{id}/`, `rig_calibration_{id}.png`. A default like
`spec.get("id", "shot-01")` therefore does not merely pick a label — it
collapses every shot that lacks an id onto ONE namespace, so shot A's frames
are silently overwritten by shot B's.

The engine's rule is "no implicit defaults": a value the spec does not
declare must fail loudly. These tests pin that for `id`:

* production code must not read `id` through a defaulting `.get`;
* the two commands that read a spec straight off disk (without
  `load_spec`/`validate`) must reject a spec with no id.

Only `spec.get("id")` with NO default is allowed — that yields None, which
callers must handle explicitly.
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Files that read the shot id and therefore must never default it.
PRODUCTION_FILES = [
    "stages/02_prepare.py",
    "stages/03_compose.py",
    "stages/04_gate.py",
    "stages/05_inspect.py",
    "core/generation/uploads.py",
    "core/rendering/encoding.py",
    "core/rendering/remotion.py",
    "core/rig/verification/puppet.py",
    "pipeline.py",
]


def _parse(rel):
    path = os.path.join(ROOT, rel)
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


def _spec_get_calls(tree):
    """Every `spec.get('id', ...)` / `spec_data.get('id', ...)` call in the tree.

    A call that passes NO default is fine (it yields None and the caller must
    handle it). A call that passes a default is the defect this file guards.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "get":
            continue
        if not isinstance(func.value, ast.Name):
            continue
        if func.value.id not in ("spec", "spec_data"):
            continue
        if not node.args:
            continue
        key = node.args[0]
        if isinstance(key, ast.Constant) and key.value == "id":
            found.append((func.value.id, node.lineno, len(node.args)))
    return found


class NoImplicitShotIdDefaultTests(unittest.TestCase):
    def test_01_production_code_never_defaults_the_shot_id(self):
        """No `spec.get('id', <default>)` anywhere in production code.

        Checked structurally (AST) rather than by text so a mention in a
        comment or a docstring cannot satisfy the check, and cannot trip it
        either.
        """
        offenders = []
        for rel in PRODUCTION_FILES:
            tree = _parse(rel)
            for _var, lineno, argc in _spec_get_calls(tree):
                if argc > 1:
                    offenders.append(f"{rel}:{lineno}")
        self.assertEqual(
            offenders, [],
            "the shot id must not be defaulted — a default collapses every "
            "id-less shot onto one asset namespace: " + ", ".join(offenders))

    def test_02_a_defaultless_get_is_still_allowed(self):
        """`spec.get('id')` (no default) is fine — it yields None explicitly.

        Guards the guard: the check above must not be satisfied by banning the
        call outright, and must not flag the harmless form.
        """
        tree = _parse("core/audio/sync.py")
        calls = _spec_get_calls(tree)
        self.assertTrue(calls, "sync.py reads the shot id")
        for _var, _lineno, argc in calls:
            self.assertEqual(argc, 1,
                             "sync.py must read the id without a default")


class DetectPunchesRejectsAMissingIdTests(unittest.TestCase):
    """`detect-punches` reads the spec directly and never sees validate().

    That makes it the one command where a defaulted id is genuinely live:
    everything else goes through `load_spec`, which already rejects a spec
    with no id.
    """

    def _run_cli(self, spec):
        import subprocess
        import sys
        import tempfile
        import json as _json

        with tempfile.TemporaryDirectory() as tmp:
            spec_path = os.path.join(tmp, "no-id.poster.json")
            with open(spec_path, "w") as f:
                _json.dump(spec, f)
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "pipeline.py"),
                 "detect-punches", "--spec", spec_path],
                capture_output=True, text=True, cwd=ROOT)
            return proc

    def test_03_detect_punches_rejects_a_spec_without_an_id(self):
        proc = self._run_cli({
            "canvas": {"w": 10, "h": 10}, "fps": 30,
            "durationInFrames": 30, "layers": [], "gates": [],
        })
        self.assertNotEqual(proc.returncode, 0,
                            "a spec with no id must not be accepted")
        combined = (proc.stdout or "") + (proc.stderr or "")
        self.assertIn("'id'", combined,
                      "the error must name the missing field: " + combined)

    def test_04_detect_punches_accepts_a_spec_with_an_id(self):
        """The guard must not reject a valid spec — the id is what it names."""
        import json as _json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            spec_path = os.path.join(tmp, "with-id.poster.json")
            with open(spec_path, "w") as f:
                _json.dump({
                    "id": "shot-42", "canvas": {"w": 10, "h": 10}, "fps": 30,
                    "durationInFrames": 30, "layers": [], "gates": [],
                }, f)
            # The audio file it looks for does not exist, so it must fail on
            # the MISSING FILE (not on the id) — that proves the id passed.
            import subprocess
            import sys
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "pipeline.py"),
                 "detect-punches", "--spec", spec_path],
                capture_output=True, text=True, cwd=ROOT)
            combined = (proc.stdout or "") + (proc.stderr or "")
            self.assertNotIn("missing a non-empty 'id'", combined,
                             "a spec WITH an id must pass the id check: "
                             + combined)


if __name__ == "__main__":
    unittest.main()
