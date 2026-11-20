"""Broadcast-grade mastering.

- run_two_pass_loudnorm: Two-pass EBU R128 loudness normalization to I=-16 LUFS, TP=-1.5 dBTP, LRA=11
"""
import json
import math
import os
import re
import subprocess
from core.runtime.timeouts import LOCAL_TOOL_TIMEOUT

def run_two_pass_loudnorm(input_args, filter_flag, base_filter, target_duration, out_path,
                          codec_args=("-c:a", "aac", "-b:a", "192k")):
    """Two-pass EBU R128 loudness normalization to I=-16 LUFS, TP=-1.5 dBTP, LRA=11.

    Single-pass loudnorm operates in dynamic mode where short speech over a longer
    shot (or varying speech density) drifts between -16.9 and -11.7 LUFS, failing
    both the per-shot [-19, -13] gate and the concat loudness_jump <= 3.0 LU gate.
    Pass 1 measures input_i/input_tp/input_lra/input_thresh/target_offset via
    -f null, and Pass 2 applies those exact measurements while pinning 44100 Hz
    stereo output with linear=true.
    """
    ln_base = "loudnorm=I=-16:TP=-1.5:LRA=11"
    pass1_chain = f"{base_filter},{ln_base}:print_format=json" if base_filter else f"{ln_base}:print_format=json"
    dur_args = ["-t", str(target_duration)] if target_duration is not None else []
    pass1_cmd = (
        ["ffmpeg", "-hide_banner", "-nostats"]
        + list(input_args)
        + [filter_flag, pass1_chain, "-ar", "44100"]
        + dur_args
        + ["-f", "null", "-"]
    )
    res1 = subprocess.run(pass1_cmd, capture_output=True, text=True,
                          timeout=LOCAL_TOOL_TIMEOUT)
    ln_pass2 = ln_base
    matches = re.findall(r"\{\s*\"input_i\"[\s\S]*?\}", (res1.stderr or "") + (res1.stdout or ""))
    if matches:
        try:
            stats = json.loads(matches[-1])
            keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
            vals = [stats.get(k) for k in keys]
            if all(v is not None and str(v).strip().lower() not in ("-inf", "inf", "nan", "") for v in vals):
                fvals = [float(v) for v in vals]
                if all(math.isfinite(fv) for fv in fvals):
                    ln_pass2 = (
                        f"{ln_base}:"
                        f"measured_I={vals[0]}:measured_TP={vals[1]}:"
                        f"measured_LRA={vals[2]}:measured_thresh={vals[3]}:"
                        f"offset={vals[4]}:linear=true"
                    )
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    pass2_chain = f"{base_filter},{ln_pass2}" if base_filter else ln_pass2
    pass2_cmd = (
        ["ffmpeg", "-v", "error", "-y"]
        + list(input_args)
        + [filter_flag, pass2_chain, "-ar", "44100", "-ac", "2"]
        + dur_args
        + list(codec_args)
        + [out_path]
    )
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    subprocess.run(pass2_cmd, check=True, timeout=LOCAL_TOOL_TIMEOUT)
    return out_path
