"""Inverse kinematics, spring dynamics, and scalar track evaluation."""
import math


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
    """
    if total_frames <= 1:
        return [[0, 0.0]]

    dt_frame = 1.0 / max(1.0, float(fps))
    substeps = 4
    dt = dt_frame / substeps
    clamp_a = max(1.0, float(max_accel))

    u = [eval_channel(driver_kfs, f, 0.0) for f in range(total_frames)]
    r = [eval_channel(base_kfs, f, 0.0) if base_kfs else 0.0 for f in range(total_frames)]

    accel = [0.0] * total_frames
    for f in range(1, total_frames - 1):
        a = (u[f + 1] - 2.0 * u[f] + u[f - 1]) / (dt_frame * dt_frame)
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
    """Linearly interpolate a scalar keyframe track at a given frame."""
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
            t = (frame - k0[0]) / max(1, k1[0] - k0[0])
            return float(k0[1]) + (float(k1[1]) - float(k0[1])) * t
    return fallback
