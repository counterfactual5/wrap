import unittest
import math
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.rig import solve_2bone_ik, solve_leg_ground_lock, verify_combat_contact


class TestRigIKAndChoreography(unittest.TestCase):
    def test_01_solve_2bone_ik_reachable(self):
        """Test basic 2-bone IK solver for a typical leg (thigh=150, calf=150)."""
        hip = [200, 200]
        # Foot directly below at distance 240 (reachable since 240 < 300)
        foot = [200, 440]
        L1, L2 = 150, 150
        res = solve_2bone_ik(hip, foot, L1, L2, bend_dir=1)

        self.assertTrue(res["reachable"])
        # Check that knee point and foot point match distances
        kx, ky = res["knee"]
        d_hip_knee = math.dist(hip, [kx, ky])
        d_knee_foot = math.dist([kx, ky], foot)
        self.assertAlmostEqual(d_hip_knee, L1, delta=0.5)
        self.assertAlmostEqual(d_knee_foot, L2, delta=0.5)
        # Knee should bend forward (bend_dir=1 -> kx > hip[0])
        self.assertGreater(kx, hip[0])

    def test_02_solve_2bone_ik_unreachable_clamped(self):
        """When foot target is beyond reach, solver clamps along ray without NaN."""
        hip = [100, 100]
        foot = [100, 500]  # dist = 400 > 120 + 120
        L1, L2 = 120, 120
        res = solve_2bone_ik(hip, foot, L1, L2, bend_dir=1)
        self.assertFalse(res["reachable"])
        # Leg should be fully extended along hip-to-foot direction
        self.assertAlmostEqual(res["knee_angle"], 0.0, delta=1.0)

    def test_03_ground_locking_preserves_foot_height(self):
        """As hip lowers (crouch), IK rotates thigh and calf so foot y stays locked at ground_y."""
        ground_y = 600
        foot_x = 250
        L1, L2 = 160, 160

        # High hip (standing)
        res_stand = solve_leg_ground_lock(hip_x=220, hip_y=350, ground_y=ground_y, foot_offset_x=30, L1=L1, L2=L2)
        # Low hip (crouching)
        res_crouch = solve_leg_ground_lock(hip_x=220, hip_y=420, ground_y=ground_y, foot_offset_x=30, L1=L1, L2=L2)

        self.assertTrue(res_stand["reachable"])
        self.assertTrue(res_crouch["reachable"])
        # In crouch, thigh must rotate more forward/outward and knee bend more
        self.assertGreater(abs(res_crouch["knee_angle"]), abs(res_stand["knee_angle"]))


    def test_05_combat_contact_verification(self):
        """Combat contact verification passes when weapon reaches target, and fails when whiffing."""
        # Spec with whiffing (gap > 40px)
        whiff_spec = {
            "tracks": {"events": [{"frame": 62, "kind": "contact"}]},
            "combat": {"attacker": "hero", "weapon": "hero-armstaff", "target": "enemy",
                       "tolerance": 40, "tipOffset": [535.0, -268.0], "refWidth": 1090.0},
            "layers": [
                {"id": "hero", "rect": [400, 500, 100, 200], "anim": {"x": [[0, 0], [62, 0]]}},
                {"id": "hero-armstaff", "rect": [400, 500, 300, 300], "pivot": [450, 550], "anim": {"rotate": [[0, 0], [62, 50]]}},
                {"id": "enemy", "rect": [1200, 500, 200, 300], "anim": {"x": [[0, 0], [62, 0]]}}
            ]
        }
        res_fail = verify_combat_contact(whiff_spec, tolerance=40)
        self.assertFalse(res_fail["passed"])
        self.assertIn("misses target", res_fail["errors"][0])

        # Spec with contact (weapon reaches target)
        hit_spec = {
            "tracks": {"events": [{"frame": 62, "kind": "contact"}]},
            "combat": {"attacker": "hero", "weapon": "hero-armstaff", "target": "enemy",
                       "tolerance": 40, "tipOffset": [535.0, -268.0], "refWidth": 1090.0},
            "layers": [
                {"id": "hero", "rect": [540, 485, 104, 280], "anim": {"x": [[0, 0], [62, 260]]}},
                {"id": "hero-armstaff", "rect": [327, 440, 476, 530], "pivot": [583.9, 606.8], "anim": {"rotate": [[0, 0], [62, 50]]}},
                {"id": "enemy", "rect": [880, 509, 246, 330], "anim": {"x": [[0, 0], [62, 20]]}}
            ]
        }
        res_pass = verify_combat_contact(hit_spec, tolerance=40)
        self.assertTrue(res_pass["passed"])
        self.assertEqual(res_pass["details"][0]["status"], "DIRECT_HIT")

    def test_06_secondary_spring_damper_physics(self):
        """Second-order spring-damper solver produces inertial lag and damped ring-out on snap stop."""
        from core.rig import solve_spring_damper_track

        # Driver snaps from 0 to +60 between f=10 and f=16, then holds flat
        driver_kfs = [[0, 0], [10, 0], [16, 60, "snap"], [60, 60]]
        track = solve_spring_damper_track(driver_kfs, total_frames=60, fps=30, omega=20.0, zeta=0.22, coupling=0.45)
        self.assertGreater(len(track), 10)
        vals = [v for _, v in track]
        # Must exhibit both negative and positive oscillations (damped harmonic ring-out)
        self.assertLess(min(vals), -1.0)
        self.assertGreater(max(vals), 1.0)
        # By frame 58, oscillation should have damped near rest (0.0)
        self.assertAlmostEqual(vals[-1], 0.0, delta=3.0)





    def test_11b_verify_combat_refuses_to_guess_weapon_geometry(self):
        """Zero guessed fallbacks: missing tipOffset/refWidth is an explicit error."""
        from core.rig.verification.combat import verify_combat_contact
        spec = {
            "tracks": {"events": [{"frame": 10, "kind": "contact"}]},
            "combat": {"attacker": "hero", "weapon": "staff", "target": "enemy"},
            "layers": [
                {"id": "hero", "rect": [0, 0, 100, 200], "anim": {"x": [[0, 0], [10, 0]]}},
                {"id": "staff", "rect": [0, 0, 300, 300], "pivot": [50, 50], "anim": {"rotate": [[0, 0], [10, 0]]}},
                {"id": "enemy", "rect": [600, 0, 200, 300], "anim": {"x": [[0, 0], [10, 0]]}},
            ],
        }
        res = verify_combat_contact(spec)
        self.assertFalse(res["passed"])
        self.assertTrue(any("tipOffset" in e for e in res["errors"]), res["errors"])

    def test_11_verify_combat_missing_layers_no_keyerror(self):
        """P1-3: verify_combat_contact and CLI verify-combat return clean error without KeyError: 'details'."""
        import subprocess
        import tempfile
        import json

        spec = {
            "id": "no-combat-shot",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [
                {"id": "bg", "type": "component", "component": "TestGraphic", "rect": [0, 0, 1080, 1920], "z": 0},
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.5}],
        }
        res = verify_combat_contact(spec)
        self.assertFalse(res["passed"])
        self.assertIn("details", res)
        self.assertEqual(res["details"], [])

        with tempfile.TemporaryDirectory() as tmp:
            spec_p = os.path.join(tmp, "no-combat.poster.json")
            with open(spec_p, "w") as f:
                json.dump(spec, f)
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "pipeline.py"), "verify-combat", "--spec", spec_p],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertNotIn("KeyError", proc.stderr)
            self.assertIn("Missing attacker, weapon, or target layer in spec", proc.stdout)

    def test_12_init_shot_from_shot_respects_poster_root(self):
        """P1-4: init-shot --from-shot resolves relative paths under POSTER_ROOT even when CWD is engine ROOT."""
        import subprocess
        import tempfile
        import json

        with tempfile.TemporaryDirectory() as proj_dir:
            os.makedirs(os.path.join(proj_dir, "spec"), exist_ok=True)
            prev_spec = {
                "id": "shot-07",
                "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
                "fps": 30,
                "durationInFrames": 90,
                "layers": [
                    {
                        "id": "hero",
                        "type": "ai",
                        "asset": "hero-base",
                        "keyColor": "#ffffff",
                        "blend": "normal",
                        "rect": [240, 480, 600, 900],
                        "z": 1,
                        "poses": [{"frame": 0, "asset": "hero-base"}, {"frame": 45, "asset": "hero-pose-b"}],
                        "anim": {"x": [[0, 0], [89, 120]], "y": [[0, 0], [89, -30]]},
                    }
                ],
                "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.5}],
            }
            with open(os.path.join(proj_dir, "spec", "shot-07.poster.json"), "w") as f:
                json.dump(prev_spec, f)

            env = dict(os.environ, POSTER_ROOT=proj_dir)
            proc = subprocess.run(
                [
                    sys.executable,
                    os.path.join(ROOT, "pipeline.py"),
                    "init-shot",
                    "shot-08", "--canvas", "1080", "1920", "--fps", "30", "--frames", "90",
                    "--from-shot",
                    "spec/shot-07.poster.json",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out_path = os.path.join(proj_dir, "spec", "shot-08.poster.json")
            self.assertTrue(os.path.exists(out_path))
            with open(out_path) as f:
                s08 = json.load(f)
            self.assertEqual(s08["id"], "shot-08")
            hero_l = s08["layers"][0]
            self.assertEqual(hero_l["asset"], "hero-pose-b")
            self.assertEqual(hero_l["poses"], [{"frame": 0, "asset": "hero-pose-b"}])
            self.assertEqual(hero_l["anim"]["x"][0], [0, 120])
            self.assertEqual(hero_l["anim"]["y"][0], [0, -30])

    def test_13_continuity_root_character_states_use_canvas_coords(self):
        """P1-5: _extract_root_character_states uses rect[0]+anim.x so non-stage shots don't false-positive at x=0.0."""
        from core.rig import _extract_root_character_states, verify_timeline_continuity
        import tempfile
        import json

        s04 = {
            "id": "shot-04",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [
                {"id": "bg", "type": "component", "component": "TestGraphic", "rect": [0, 0, 1080, 1920], "z": 0},
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.5}],
        }
        s05 = {
            "id": "shot-05",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [
                {
                    "id": "body",
                    "type": "ai",
                    "asset": "monk-body",
                    "keyColor": "#ffffff",
                    "blend": "normal",
                    "cutout": True,
                    "cutoutSimilarity": 0.14,
                    "cutoutBlend": 0.06,
                    "rect": [240, 480, 600, 900],
                    "z": 1,
                }
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.5}],
        }
        states_0 = _extract_root_character_states(s05, 0)
        self.assertEqual(states_0["body"]["x"], 240.0)
        self.assertEqual(states_0["body"]["y"], 480.0)
        self.assertEqual(states_0["body"]["dx"], 0.0)

        with tempfile.TemporaryDirectory() as tmp:
            p04 = os.path.join(tmp, "shot-04.poster.json")
            p05 = os.path.join(tmp, "shot-05.poster.json")
            with open(p04, "w") as f:
                json.dump(s04, f)
            with open(p05, "w") as f:
                json.dump(s05, f)
            tl_data = {
                "id": "test-tl",
                "shots": [
                    {"spec": p04, "beat": "hook", "reason": "a"},
                    {"spec": p05, "beat": "development", "reason": "b"},
                ],
            }
            rep = verify_timeline_continuity(tl_data, root_dir=tmp)
            self.assertEqual(rep["handoffs"][0]["char_jumps"], [])






class TestBlockingNoGuessedBands(unittest.TestCase):
    """verify-blocking must measure torso bands, never assume 20-80%."""

    def test_assetless_character_without_blockcore_fails(self):
        from core.rig import verify_stage_blocking
        spec = {
            "id": "lane",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 30,
            "layers": [
                {"id": "a", "type": "ai", "asset": "a.png", "cutout": True, "cutoutSimilarity": 0.14, "cutoutBlend": 0.06,
                 "keyColor": "#ffffff", "blend": "normal", "rect": [10, 0, 200, 400], "z": 1},
                {"id": "b", "type": "ai", "asset": "b.png", "cutout": True, "cutoutSimilarity": 0.14, "cutoutBlend": 0.06,
                 "keyColor": "#ffffff", "blend": "normal", "rect": [40, 0, 200, 400], "z": 2},
            ],
            "gates": [],
        }
        res = verify_stage_blocking(spec)
        self.assertFalse(res["passed"], res)
        self.assertTrue(any("blockCore" in e for e in res["errors"]), res["errors"])

    def test_assetless_character_with_blockcore_measured(self):
        from core.rig import verify_stage_blocking
        spec = {
            "id": "lane",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 30,
            "layers": [
                {"id": "a", "type": "ai", "asset": "a.png", "cutout": True, "blockCore": [0.25, 0.75],
                 "keyColor": "#ffffff", "blend": "normal", "cutoutSimilarity": 0.14, "cutoutBlend": 0.06,
                 "rect": [100, 0, 200, 400], "z": 1},
                {"id": "b", "type": "ai", "asset": "b.png", "cutout": True, "blockCore": [0.25, 0.75],
                 "keyColor": "#ffffff", "blend": "normal", "cutoutSimilarity": 0.14, "cutoutBlend": 0.06,
                 "rect": [700, 0, 200, 400], "z": 2},
            ],
            "gates": [],
        }
        res = verify_stage_blocking(spec)
        self.assertTrue(res["passed"], res)


if __name__ == "__main__":
    unittest.main()
