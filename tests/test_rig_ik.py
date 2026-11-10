import unittest
import math
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
        from core.schema import validate

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
        from core.schema import validate

        # 1. Non-hero layer with role='humanoid' and only 1 arm must trigger anatomical check
        bad_humanoid_spec = {
            "id": "test-nezha",
            "canvas": {"w": 1920, "h": 1080},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [
                {
                    "id": "nezha",
                    "type": "code",
                    "draw": "bar",
                    "role": "humanoid",
                    "color": "#ffaa00",
                    "rect": [200, 200, 200, 300],
                    "z": 2,
                },
                {
                    "id": "nezha-arm-spear",
                    "type": "code",
                    "draw": "bar",
                    "parent": "nezha",
                    "color": "#ffaa00",
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
                    "type": "code",
                    "draw": "bar",
                    "color": "#00aaff",
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
                    "type": "code",
                    "draw": "bar",
                    "parent": "knight",
                    "color": "#00aaff",
                    "rect": [400, 400, 400, 100],
                    "pivot": [450, 450],
                    "z": 3,
                    "anim": {"rotate": [[0, 0], [30, 15]]},
                },
                {
                    "id": "dragon",
                    "type": "code",
                    "draw": "bar",
                    "color": "#ff3300",
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


if __name__ == "__main__":
    unittest.main()
