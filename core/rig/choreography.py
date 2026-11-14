"""Parametric puppet choreography keyframe generation."""


def generate_puppet_choreography(beats, default_ground_y=720):
    """Generate physically-coordinated keyframe tracks for an articulated puppet.

    Produces synchronized keyframes for:
    - torso: x, y, rotate (center of gravity & weight shifts)
    - leg-front: rotate (stepping, crouching, kicking with ground contact)
    - leg-back: rotate (stance anchoring, lunging, pushing)
    - arm-front: rotate (weapon swings, thrusts, aerial raises)
    - arm-back: rotate (counter-phase martial balance, 亮掌/甩袖)
    - plume: rotate (inertial lag & harmonic settlement)
    """
    torso_x = []
    torso_y = []
    torso_rot = []
    leg_front_rot = []
    leg_back_rot = []
    arm_front_rot = []
    arm_back_rot = []
    plume_rot = []

    for b in beats:
        btype = b.get("type", "ready")
        f_start = b["start"]
        f_end = b["end"]
        ground_y = b.get("ground_y", default_ground_y)

        if btype == "ready":
            # Classic Opera Wusheng Stance (虚步就绪):
            # Front foot light on toe (-5°), back foot supporting 70% weight (15°).
            # Rear arm extended behind back in martial balance (+30°), front arm holding staff (0°).
            rx = b.get("root_x", 450)
            torso_x.append([f_start, rx])
            torso_y.append([f_start, 0])
            torso_rot.append([f_start, 0])
            leg_front_rot.append([f_start, -5])
            leg_back_rot.append([f_start, 15])
            arm_front_rot.append([f_start, 0])
            arm_back_rot.append([f_start, 30])
            plume_rot.append([f_start, -8])

            if f_end > f_start:
                torso_x.append([f_end, rx])
                torso_y.append([f_end, 0])
                torso_rot.append([f_end, 0])
                leg_front_rot.append([f_end, -5])
                leg_back_rot.append([f_end, 15])
                arm_front_rot.append([f_end, 0])
                arm_back_rot.append([f_end, 30])
                plume_rot.append([f_end, -8])

        elif btype == "strike":
            # Three-Phase Martial Strike:
            # 1. Anticipation (蓄力): Torso lowers and pulls back, front staff raises overhead (-55°),
            #    rear arm counterbalances forward (-20°), front knee lifts (-28°), back leg extends (22°).
            # 2. Impact Snap (千钧暴击): Torso lunges down-forward into 弓步 (bow stance),
            #    front staff slams down level (40°), rear arm snaps back hard (+50° ~ +55°),
            #    front leg bends deep (20°), back leg straightens (-18°).
            # 3. Follow-through / Recoil (收势与定点): slight rebound into guard.
            f_ant = b.get("anticipation", int(f_start + (f_end - f_start) * 0.45))
            f_hit = b.get("impact", int(f_start + (f_end - f_start) * 0.75))
            x_start = b.get("root_x_start", 450)
            x_end = b.get("root_x_end", 800)

            # --- Anticipation Frame ---
            torso_x.append([f_ant, int(x_start + (x_end - x_start) * 0.35), "out"])
            torso_y.append([f_ant, -15, "out"])  # slight aerial lift or crouch
            torso_rot.append([f_ant, -10, "out"]) # leaning back
            leg_front_rot.append([f_ant, -28, "out"])
            leg_back_rot.append([f_ant, 22, "out"])
            arm_front_rot.append([f_ant, -55, "out"]) # weapon raised high
            arm_back_rot.append([f_ant, -20, "out"])  # counter-swings forward
            plume_rot.append([f_ant, 15, "out"])      # dragged back by air resistance

            # --- Impact Frame ---
            torso_x.append([f_hit, x_end, "in"])
            torso_y.append([f_hit, 0, "in"])
            torso_rot.append([f_hit, 8, "in"])        # lunging forward into strike
            leg_front_rot.append([f_hit, 20, "in"])   # bow stance (弓步屈膝)
            leg_back_rot.append([f_hit, -16, "in"])  # arrow leg straight (箭步绷直)
            arm_front_rot.append([f_hit, 40, "snap"]) # lethal snap down
            arm_back_rot.append([f_hit, 48, "snap"])  # rear balance snap backwards!
            plume_rot.append([f_hit, -22, "snap"])    # whipped forward on sudden stop

            # --- Recoil / Settle Frame ---
            if f_end > f_hit:
                torso_x.append([f_end, int(x_end - 25), "out"])
                torso_y.append([f_end, 0, "out"])
                torso_rot.append([f_end, 2, "out"])
                leg_front_rot.append([f_end, 0, "out"])
                leg_back_rot.append([f_end, 15, "out"])
                arm_front_rot.append([f_end, 10, "out"])
                arm_back_rot.append([f_end, 32, "out"])
                plume_rot.append([f_end, -10, "out"])

    return {
        "torso": {
            "x": torso_x,
            "y": torso_y,
            "rotate": torso_rot,
        },
        "leg-front": {
            "rotate": leg_front_rot,
        },
        "leg-back": {
            "rotate": leg_back_rot,
        },
        "arm-front": {
            "rotate": arm_front_rot,
        },
        "arm-back": {
            "rotate": arm_back_rot,
        },
        "plume": {
            "rotate": plume_rot,
        },
    }
