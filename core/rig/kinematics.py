"""Inverse kinematics, spring dynamics, and scalar track evaluation."""
import math

from core.spec.constants import ANIM_EASES


def apply_ease(t, ease):
    """Evaluate an easing curve at normalized time `t`.

    This is the Python twin of ``applyEase`` in remotion/kinematics.ts — the
    renderer is the authoritative reference, because the validators must gate
    the pixels that are actually rendered. Both sides implement the same seven
    curves (the vocabulary lives in ``core.spec.constants.ANIM_EASES``):

        linear      t
        in          t^2
        out         1 - (1 - t)^2
        inout       2t^2 (t < 0.5) else 1 - (-2t + 2)^2 / 2
        snap        1 - (1 - t)^4
        overshoot   1 + c3(t-1)^3 + c1(t-1)^2, c1 = 1.70158, c3 = c1 + 1
        step        0 (t < 1) else 1

    An ease outside ``ANIM_EASES`` is rejected instead of silently easing as
    linear; such a spec is already refused by ``core.spec.channels``.
    """
    if ease == "linear":
        return t
    if ease == "in":
        return t * t
    if ease == "out":
        return 1.0 - (1.0 - t) * (1.0 - t)
    if ease == "inout":
        return 2.0 * t * t if t < 0.5 else 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0
    if ease == "snap":
        return 1.0 - (1.0 - t) ** 4
    if ease == "overshoot":
        c1 = 1.70158
        c3 = c1 + 1.0
        return 1.0 + c3 * (t - 1.0) ** 3 + c1 * (t - 1.0) ** 2
    if ease == "step":
        return 0.0 if t < 1.0 else 1.0
    raise ValueError(f"unknown ease {ease!r}; expected one of {sorted(ANIM_EASES)}")


def solve_2bone_ik(hip, foot, L1, L2, bend_dir=1):
    """Analytic 2-bone Inverse Kinematics solver (thigh -> knee -> foot).

    Parameters:
    - hip: [hx, hy] hip socket coordinates
    - foot: [fx, fy] target foot contact coordinates
    - L1: length of upper segment (thigh)
    - L2: length of lower segment (calf + foot)
    - bend_dir: +1 (knee bends forward/right) or -1 (knee bends backward/left)

    Returns:
    - thigh_angle: angle of thigh relative to vertical (pointing down), in degrees
    - knee_angle: relative bend angle at knee joint, in degrees
    - knee: [kx, ky] calculated 2D knee joint position
    - foot: [fx, fy] actual foot position (coincident with target if reachable)
    - reachable: True if target was within reach (dist <= L1 + L2)
    """
    hx, hy = hip
    fx, fy = foot
    dx = fx - hx
    dy = fy - hy
    dist = math.hypot(dx, dy)

    # Ray angle from hip to target
    theta_base = math.atan2(dy, dx)

    # Target beyond reach: fully extended along ray
    if dist >= (L1 + L2) - 1e-4:
        kx = hx + L1 * math.cos(theta_base)
        ky = hy + L1 * math.sin(theta_base)
        act_fx = hx + (L1 + L2) * math.cos(theta_base)
        act_fy = hy + (L1 + L2) * math.sin(theta_base)
        thigh_angle = math.degrees(theta_base - math.pi / 2.0)
        return {
            "thigh_angle": round(thigh_angle, 2),
            "knee_angle": 0.0,
            "knee": [round(kx, 1), round(ky, 1)],
            "foot": [round(act_fx, 1), round(act_fy, 1)],
            "reachable": False,
        }

    # Target collapsed inside minimum reach:
    min_reach = abs(L1 - L2) + 1e-3
    if dist < min_reach:
        dist = min_reach

    # Law of Cosines:
    # L2^2 = L1^2 + dist^2 - 2 * L1 * dist * cos(alpha)
    cos_alpha = (L1 * L1 + dist * dist - L2 * L2) / (2.0 * L1 * dist)
    cos_alpha = max(-1.0, min(1.0, cos_alpha))
    alpha = math.acos(cos_alpha)

    # dist^2 = L1^2 + L2^2 - 2 * L1 * L2 * cos(beta)
    cos_beta = (L1 * L1 + L2 * L2 - dist * dist) / (2.0 * L1 * L2)
    cos_beta = max(-1.0, min(1.0, cos_beta))
    beta = math.acos(cos_beta)

    # Thigh direction:
    theta_thigh = theta_base - bend_dir * alpha
    kx = hx + L1 * math.cos(theta_thigh)
    ky = hy + L1 * math.sin(theta_thigh)

    # Calf direction:
    theta_calf = math.atan2(fy - ky, fx - kx)
    rel_knee = math.degrees(theta_calf - theta_thigh)
    # Normalize to [-180, 180]
    while rel_knee > 180:
        rel_knee -= 360
    while rel_knee < -180:
        rel_knee += 360

    thigh_angle = math.degrees(theta_thigh - math.pi / 2.0)
    return {
        "thigh_angle": round(thigh_angle, 2),
        "knee_angle": round(rel_knee, 2),
        "knee": [round(kx, 1), round(ky, 1)],
        "foot": [round(fx, 1), round(fy, 1)],
        "reachable": True,
    }


def solve_leg_ground_lock(hip_x, hip_y, ground_y, foot_offset_x, L1, L2, bend_dir=1):
    """Lock a puppet's foot to the ground plane while the hip moves dynamically."""
    foot_x = hip_x + foot_offset_x
    foot_y = ground_y
    return solve_2bone_ik([hip_x, hip_y], [foot_x, foot_y], L1, L2, bend_dir=bend_dir)


def solve_spring_damper_track(driver_kfs, total_frames, fps, omega, zeta,
                              coupling, base_kfs=None, step_frames=2, max_accel=4500.0):
    """Simulate a 2nd-order damped spring-mass oscillator driven by parent acceleration.

    Models secondary appendages (pheasant plumes, silk ribbons, tassels, or chart needles)
    under the differential equation:
        theta'' + 2 * zeta * omega * theta' + omega^2 * (theta - theta_rest) = -coupling * u''(t)

    where u(t) is the primary bone's motion track (`driver_kfs`) and theta_rest(t) is the
    optional baseline orientation (`base_kfs`). When the primary bone accelerates or snaps
    to a sudden halt (`亮相`), the appendage naturally lags behind and rings out with realistic
    damped rod-tremor (`抖签`) oscillation.

    This is the *offline* baker: it returns a keyframe track that an author
    drops into a layer's `anim` channel, after which the renderer interpolates
    it like any other track. The renderer's live spring (computeSpringOffset in
    remotion/kinematics.ts) solves the same equation without a rest pose, and
    with `base_kfs=None` the two agree frame for frame — see
    tests/core/test_kinematics_parity.py.
    """
    if total_frames <= 1:
        return [[0, 0.0]]

    dt_frame = 1.0 / max(1.0, float(fps))
    substeps = 4
    dt = dt_frame / substeps
    clamp_a = max(1.0, float(max_accel))

    u = [eval_channel(driver_kfs, f, 0.0) for f in range(total_frames)]
    r = [eval_channel(base_kfs, f, 0.0) if base_kfs else 0.0 for f in range(total_frames)]

    # The renderer differentiates the driver track with a central difference
    # whose "next" sample is read one frame past the track (clamped to the last
    # keyframe only when the track ends earlier) — including on the final
    # frame. Mirror that exactly, so an offline bake and the live spring land
    # on the same number.
    accel = [0.0] * total_frames
    u_next_after_end = eval_channel(driver_kfs, total_frames, 0.0)
    for f in range(1, total_frames):
        u_next = u[f + 1] if f + 1 < total_frames else u_next_after_end
        a = (u_next - 2.0 * u[f] + u[f - 1]) / (dt_frame * dt_frame)
        accel[f] = max(-clamp_a, min(clamp_a, a))

    theta = r[0]
    vel = 0.0
    out_kfs = []

    for f in range(total_frames):
        target_r = r[f]
        drv_a = accel[f]
        for _ in range(substeps):
            force = -coupling * drv_a - 2.0 * zeta * omega * vel - (omega * omega) * (theta - target_r)
            vel += force * dt
            theta += vel * dt
        if f == 0 or f == total_frames - 1 or f % max(1, int(step_frames)) == 0:
            out_kfs.append([f, round(theta, 2)])

    return out_kfs


def eval_channel(kfs, frame, fallback=0.0):
    """Evaluate a scalar keyframe track at a given frame.

    The Python twin of ``channelValue`` in remotion/kinematics.ts: a keyframe
    is ``[frame, value]`` or ``[frame, value, ease]``, and the ease of the
    *segment's last* keyframe shapes that segment (a two-element keyframe
    eases as linear). The segment is normalized by ``max(1e-6, dt)`` exactly
    as the renderer does, so the validators measure the same world the
    renderer draws.
    """
    if not kfs:
        return fallback
    if frame <= kfs[0][0]:
        return float(kfs[0][1])
    if frame >= kfs[-1][0]:
        return float(kfs[-1][1])
    for i in range(len(kfs) - 1):
        k0 = kfs[i]
        k1 = kfs[i + 1]
        if k0[0] <= frame <= k1[0]:
            span = max(1e-6, k1[0] - k0[0])
            t = (frame - k0[0]) / span
            ease = k1[2] if len(k1) > 2 and k1[2] is not None else "linear"
            return float(k0[1]) + (float(k1[1]) - float(k0[1])) * apply_ease(t, ease)
    return fallback
