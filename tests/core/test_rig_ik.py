import unittest
import math
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.rig import solve_2bone_ik, solve_leg_ground_lock, generate_puppet_choreography, verify_combat_contact


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

    def test_04_parametric_choreography_generates_quad_limbs(self):
        """Parametric choreography generator produces synchronized tracks for all 4 limbs + torso."""
        beats = [
            {"type": "ready", "start": 0, "end": 30, "root_x": 400, "ground_y": 720},
            {"type": "strike", "start": 31, "anticipation": 45, "impact": 62, "end": 80,
             "root_x_start": 400, "root_x_end": 750, "target_x": 950, "target_y": 660, "ground_y": 720}
        ]
        choreo = generate_puppet_choreography(beats)
        self.assertIn("torso", choreo)
        self.assertIn("leg-front", choreo)
        self.assertIn("leg-back", choreo)
        self.assertIn("arm-front", choreo)
        self.assertIn("arm-back", choreo)

        # Check keyframe continuity
        torso_rot = choreo["torso"]["rotate"]
        self.assertGreater(len(torso_rot), 2)
        # Check counter-phase arm balance at impact
        arm_f_hit = [v for f, v, *rest in choreo["arm-front"]["rotate"] if f == 62][0]
        arm_b_hit = [v for f, v, *rest in choreo["arm-back"]["rotate"] if f == 62][0]
        # Front arm strikes forward/down (+), back arm counterbalances backwards (+)
        self.assertGreater(arm_f_hit, 0)
        self.assertGreater(arm_b_hit, 0)

    def test_05_combat_contact_verification(self):
        """Combat contact verification passes when weapon reaches target, and fails when whiffing."""
        # Spec with whiffing (gap > 40px)
        whiff_spec = {
            "punches": [62],
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
            "punches": [62],
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

    def test_07_schema_accepts_depth_and_spring(self):
        """Schema validator accepts anim.depth in [0,1] and layer.spring parameters."""
        from core.spec.shot import validate

        spec = {
            "id": "test-depth-spring",
            "canvas": {"w": 1920, "h": 1080},
            "fps": 30,
            "durationInFrames": 90,
            "layers": [
                {
                    "id": "hero",
                    "type": "code",
                    "draw": "bar",
                    "color": "#ffaa00",
                    "rect": [100, 100, 200, 200],
                    "z": 1,
                    "spring": {"omega": 18.0, "zeta": 0.25, "coupling": 0.45},
                    "anim": {
                        "rotate": [[0, 0], [30, 45, "snap"]],
                        "depth": [[0, 0.0], [15, 0.65, "out"], [30, 0.0, "snap"]],
                    },
                }
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.5}],
        }
        errs = validate(spec)
        self.assertEqual(errs, [])

    def test_08_generalized_humanoid_role_combat_and_spring_channels(self):
        """Verify non-hero humanoid role check, spec.combat config, and multi-channel spring validation."""
        from core.spec.shot import validate

        # 1. Non-hero layer with role='humanoid' and only 1 arm must trigger anatomical check
        bad_humanoid_spec = {
            "id": "test-nezha",
            "canvas": {"w": 1920, "h": 1080},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [
                {
                    "id": "nezha",
                    "type": "ai",
                    "asset": "nezha-torso",
                    "keyColor": "#ffffff",
                    "blend": "normal",
                    "role": "humanoid",
                    "rect": [200, 200, 200, 300],
                    "z": 2,
                },
                {
                    "id": "nezha-arm-spear",
                    "type": "ai",
                    "asset": "nezha-spear",
                    "keyColor": "#ffffff",
                    "blend": "normal",
                    "parent": "nezha",
                    "rect": [220, 220, 100, 100],
                    "z": 3,
                },
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.5}],
        }
        errs_bad = validate(bad_humanoid_spec)
        self.assertTrue(any("humanoid puppet has only 1 arm" in e for e in errs_bad))

        # 2. Spec with custom combat config and multi-channel spring ('y' driven by 'y') passes validation
        good_spec = {
            "id": "test-defi-spring",
            "canvas": {"w": 1920, "h": 1080},
            "fps": 30,
            "durationInFrames": 60,
            "punches": [30],
            "combat": {
                "attacker": "knight",
                "weapon": "knight-lance",
                "target": "dragon",
                "tipOffset": [400, -100],
                "refWidth": 800,
                "tolerance": 35,
            },
            "layers": [
                {
                    "id": "knight",
                    "type": "ai",
                    "asset": "knight-body",
                    "keyColor": "#ffffff",
                    "blend": "normal",
                    "shadowColor": "#001122",
                    "translucent": False,
                    "controlRod": False,
                    "rect": [400, 400, 150, 250],
                    "z": 2,
                    "spring": {
                        "omega": 16.0,
                        "zeta": 0.3,
                        "coupling": 0.4,
                        "channel": "y",
                        "driverChannel": "y",
                        "maxAccel": 6000,
                    },
                    "anim": {"x": [[0, 0], [30, 200]], "y": [[0, 0], [30, -40, "snap"]]},
                },
                {
                    "id": "knight-lance",
                    "type": "ai",
                    "asset": "knight-lance-img",
                    "keyColor": "#ffffff",
                    "blend": "normal",
                    "parent": "knight",
                    "rect": [400, 400, 400, 100],
                    "pivot": [450, 450],
                    "z": 3,
                    "anim": {"rotate": [[0, 0], [30, 15]]},
                },
                {
                    "id": "dragon",
                    "type": "ai",
                    "asset": "dragon-body",
                    "keyColor": "#ffffff",
                    "blend": "normal",
                    "rect": [800, 400, 250, 300],
                    "z": 4,
                    "anim": {"x": [[0, 0], [30, 10]]},
                },
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.5}],
        }
        self.assertEqual(validate(good_spec), [])
        combat_res = verify_combat_contact(good_spec)
        self.assertTrue(combat_res["passed"])

    def test_09_verify_shot_stagecraft_and_scrolling_transition(self):
        """Verify in-shot scrolling backdrop transitions ('推拉换景') and narrative props ('砌末')."""
        from core.rig import verify_shot_stagecraft

        spec = {
            "id": "test-scroll-scene",
            "canvas": {"w": 1920, "h": 1080},
            "fps": 30,
            "durationInFrames": 180,
            "layers": [
                {
                    "id": "stage-frame",
                    "type": "ai",
                    "asset": "frame-plate",
                    "role": "backdrop",
                    "blend": "normal",
                    "keyColor": "#ffffff",
                    "plate": False,
                    "rect": [0, 0, 1920, 1080],
                    "z": 0,
                },
                {
                    "id": "scroll-bg-a",
                    "type": "ai",
                    "asset": "scene-forest",
                    "role": "backdrop",
                    "blend": "normal",
                    "keyColor": "#ffffff",
                    "plate": False,
                    "rect": [270, 240, 1384, 654],
                    "clipRect": [270, 240, 1384, 654],
                    "z": 1,
                    "anim": {"x": [[0, 0], [120, 0], [179, -1384, "inout"]]},
                },
                {
                    "id": "scroll-bg-b",
                    "type": "ai",
                    "asset": "scene-cliff",
                    "role": "backdrop",
                    "blend": "normal",
                    "keyColor": "#ffffff",
                    "plate": False,
                    "rect": [270, 240, 1384, 654],
                    "clipRect": [270, 240, 1384, 654],
                    "z": 2,
                    "anim": {"x": [[0, 1384], [120, 1384], [179, 0, "inout"]]},
                },
                {
                    "id": "prop-scroll",
                    "type": "ai",
                    "asset": "decree-scroll",
                    "role": "prop",
                    "cutout": True,
                    "blend": "normal",
                    "keyColor": "#ffffff",
                    "rect": [600, 500, 96, 96],
                    "z": 5,
                    "anim": {"x": [[0, 0], [90, 180, "out"]], "opacity": [[0, 0], [40, 1], [179, 1]]},
                },
                {
                    "id": "hero",
                    "type": "ai",
                    "asset": "hero-torso",
                    "role": "humanoid",
                    "cutout": True,
                    "blend": "normal",
                    "keyColor": "#ffffff",
                    "rect": [500, 420, 200, 380],
                    "z": 10,
                    "anim": {"x": [[0, 0], [179, 120, "inout"]]},
                },
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.5}],
        }
        rep = verify_shot_stagecraft(spec)
        self.assertTrue(rep["passed"])
        self.assertTrue(rep["has_in_shot_scroll"])
        self.assertEqual(rep["start_backdrop"], "scene-forest")
        self.assertEqual(rep["end_backdrop"], "scene-cliff")
        self.assertIn("prop-scroll", rep["narrative_props"])

    def test_10_stagecraft_turnaround_shudder_and_caption_sync(self):
        """Verify domain-agnostic stagecraft checks: flipX turnaround, shudder posture/bare-arm pose, and caption clause sync."""
        from core.rig import verify_shot_stagecraft
        import copy

        good_spec = {
            "id": "test-shudder-good",
            "canvas": {"w": 1920, "h": 1080},
            "fps": 30,
            "durationInFrames": 120,
            "layers": [
                {
                    "id": "caster",
                    "type": "ai",
                    "asset": "caster-body",
                    "role": "humanoid",
                    "cutout": True,
                    "rect": [300, 400, 200, 380],
                    "z": 10,
                    "anim": {"x": [[0, 0], [119, 0]]},
                },
                {
                    "id": "caster-leg-front",
                    "type": "ai",
                    "asset": "caster-leg",
                    "parent": "caster",
                    "cutout": True,
                    "rect": [300, 400, 200, 380],
                    "z": 11,
                    "anim": {"rotate": [[0, 0], [119, 0]]},
                },
                {
                    "id": "caster-arm",
                    "type": "ai",
                    "asset": "caster-arm",
                    "parent": "caster",
                    "cutout": True,
                    "rect": [300, 400, 200, 380],
                    "z": 12,
                    "anim": {"rotate": [[0, 0], [60, 22], [119, 0]]},
                },
                {
                    "id": "warrior",
                    "type": "ai",
                    "asset": "warrior-torso",
                    "role": "humanoid",
                    "cutout": True,
                    "rect": [550, 400, 200, 380],
                    "z": 20,
                    "gait": {"mode": "shudder", "freq": 15.0, "bob": 10.0, "sway": 10.0, "range": [55, 110]},
                    "anim": {
                        "flipX": [[0, 0], [50, 1, "step"], [119, 1]],
                        "y": [[0, 0], [55, 0], [75, 82, "snap"], [110, 78], [119, 0]],
                        "rotate": [[0, 0], [55, 0], [75, 42, "snap"], [110, 38], [119, 0]],
                    },
                },
                {
                    "id": "warrior-arm-spear",
                    "type": "ai",
                    "asset": "warrior-spear",
                    "parent": "warrior",
                    "cutout": True,
                    "rect": [500, 380, 300, 300],
                    "z": 21,
                    "poses": [
                        {"frame": 0, "asset": "warrior-spear"},
                        {"frame": 55, "asset": "warrior-arm-bare"},
                        {"frame": 112, "asset": "warrior-spear"},
                    ],
                    "anim": {"rotate": [[0, 0], [75, -85, "snap"], [119, 0]]},
                },
                {
                    "id": "captions",
                    "type": "code",
                    "draw": "captions",
                    "rect": [260, 960, 1400, 64],
                    "z": 30,
                    "params": {
                        "items": [
                            {"frame": 0, "text": "Clause 1: dialogue"},
                            {"frame": 52, "text": "Clause 2: incantation starts"},
                        ]
                    },
                },
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0001, "hi": 0.5}],
        }
        rep_good = verify_shot_stagecraft(good_spec)
        self.assertTrue(rep_good["passed"], rep_good)
        self.assertIn("warrior", rep_good["turnaround_characters"])

        # Bad shudder: starts mid-clause (f=28, far from 0 and 52) AND keeps holding weapon asset
        bad_spec = copy.deepcopy(good_spec)
        bad_spec["layers"][3]["gait"]["range"] = [28, 110]
        bad_spec["layers"][4]["poses"] = [{"frame": 0, "asset": "warrior-spear"}]
        rep_bad = verify_shot_stagecraft(bad_spec)
        self.assertFalse(rep_bad["passed"])
        self.assertTrue(len(rep_bad["weak_shudder_acting"]) > 0)
        self.assertTrue(len(rep_bad["caption_action_desync"]) > 0)

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
                {"id": "bg", "type": "code", "draw": "grid", "rect": [0, 0, 1080, 1920], "z": 0},
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
                    "shot-08",
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
                {"id": "bg", "type": "code", "draw": "grid", "rect": [0, 0, 1080, 1920], "z": 0},
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

    def test_14_text_flipx_mirrors_around_content_center(self):
        """P2-7: Text layers without an explicit pivot mirror around rendered text content center (width: fit-content) rather than the wide rect center."""
        with open(os.path.join(ROOT, "remotion", "Shot.tsx")) as f:
            shot_tsx = f.read()
        with open(os.path.join(ROOT, "remotion", "layers", "text.tsx")) as f:
            layers_tsx = f.read()
        self.assertIn("deferFlipToTextContent", shot_tsx)
        self.assertIn("contentFlipX", layers_tsx)
        self.assertIn("width: 'fit-content'", layers_tsx)
        self.assertIn("transformOrigin: 'center center'", layers_tsx)


if __name__ == "__main__":
    unittest.main()
