#!/usr/bin/env python3
"""Unified CLI runner for the code-driven poster video pipeline.
Commands:
  validate   Check spec against schema
  generate   S1: fetch/verify AI assets into manifest
  prepare    S2: key purity gate & scaling & code layers
  compose    S3: single-command ffmpeg composition
  gate       S4: run quality gates (motion, color, purity, freeze)
  run        Execute stages S1 -> S2 -> S3 -> S4 in sequence
  init-shot  Initialize a new shot specification template
  concat     Concatenate multiple rendered shots via timeline.json
  test       Execute full automated test suite
  clean      Clean intermediate build artifacts
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def run_stage(cmd_args, desc):
    print(f"\n=== [Stage] {desc} ===")
    res = subprocess.run([sys.executable] + cmd_args, cwd=ROOT)
    if res.returncode != 0:
        print(f"FAILED: {desc} exited with code {res.returncode}", file=sys.stderr)
        sys.exit(res.returncode)


def main():
    parser = argparse.ArgumentParser(description="Code-driven shot video pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    p_val = subparsers.add_parser("validate", help="Validate spec against schema")
    p_val.add_argument("--spec", default="spec/shot-01.poster.json")

    # generate (S1)
    p_gen = subparsers.add_parser("generate", help="S1: generate/fetch assets")
    p_gen.add_argument("--spec", default="spec/shot-01.poster.json")
    p_gen.add_argument("--force", action="store_true", help="Force re-generation")
    p_gen.add_argument("--fixture", action="store_true", help="Use deterministic fixture")

    # prepare (S2)
    p_prep = subparsers.add_parser("prepare", help="S2: prepare assets & key purity check")
    p_prep.add_argument("--spec", default="spec/shot-01.poster.json")

    # compose (S3)
    p_comp = subparsers.add_parser("compose", help="S3: ffmpeg compose frames & mp4")
    p_comp.add_argument("--spec", default="spec/shot-01.poster.json")

    # gate (S4)
    p_gate = subparsers.add_parser("gate", help="S4: quality gates & freeze detect")
    p_gate.add_argument("--spec", default="spec/shot-01.poster.json")

    # run (S1..S4)
    p_run = subparsers.add_parser("run", help="Run full pipeline: validate -> S1 -> S2 -> S3 -> S4")
    p_run.add_argument("--spec", default="spec/shot-01.poster.json")
    p_run.add_argument("--force", action="store_true", help="Force re-generation of assets")
    p_run.add_argument("--fixture", action="store_true", help="Use deterministic fixture")

    # init-shot
    p_init = subparsers.add_parser("init-shot", help="Initialize a new shot specification template")
    p_init.add_argument("shot_id", help="Shot ID, e.g. shot-02")

    # concat
    p_cat = subparsers.add_parser("concat", help="Concatenate multiple rendered shots via timeline")
    p_cat.add_argument("--timeline", default="spec/timeline.json", help="Path to timeline.json")
    p_cat.add_argument("--output", default="build/full.mp4", help="Path to output mp4")

    # test
    subparsers.add_parser("test", help="Run full regression test suite")

    # clean
    subparsers.add_parser("clean", help="Clean build artifacts")

    args = parser.parse_args()

    if args.command == "validate":
        run_stage(["schema.py", args.spec], "Spec Validation")

    elif args.command == "generate":
        gen_args = ["01_generate.py", "--spec", args.spec]
        if args.force:
            gen_args.append("--force")
        if args.fixture:
            gen_args.append("--fixture")
        run_stage(gen_args, "S1: Asset Generation / Verification")

    elif args.command == "prepare":
        run_stage(["02_prepare.py", "--spec", args.spec], "S2: Prepare & Purity Check")

    elif args.command == "compose":
        run_stage(["03_compose.py", "--spec", args.spec], "S3: Compose (FFmpeg)")

    elif args.command == "gate":
        run_stage(["04_gate.py", "--spec", args.spec], "S4: Quality Gates")

    elif args.command == "run":
        run_stage(["schema.py", args.spec], "Spec Validation")
        gen_args = ["01_generate.py", "--spec", args.spec]
        if args.force:
            gen_args.append("--force")
        if args.fixture:
            gen_args.append("--fixture")
        run_stage(gen_args, "S1: Asset Generation / Verification")
        run_stage(["02_prepare.py", "--spec", args.spec], "S2: Prepare & Purity Check")
        run_stage(["03_compose.py", "--spec", args.spec], "S3: Compose (FFmpeg)")
        run_stage(["04_gate.py", "--spec", args.spec], "S4: Quality Gates")
        print("\nPipeline completed successfully! All gates passed.")

    elif args.command == "init-shot":
        shot_id = args.shot_id.strip()
        os.makedirs(os.path.join(ROOT, "spec"), exist_ok=True)
        target = os.path.join(ROOT, "spec", f"{shot_id}.poster.json")
        if os.path.exists(target):
            print(f"Spec already exists: {target}")
            return
        template = {
            "id": shot_id,
            "canvas": {"w": 1920, "h": 1080},
            "fps": 30,
            "durationInFrames": 150,
            "style": "spec/style.json",
            "layers": [
                {"id": "bg", "type": "code", "draw": "grid", "rect": [0, 0, 1920, 1080], "z": 0},
                {"id": "subject", "type": "ai", "asset": f"{shot_id}-subject", "keyColor": "#ffffff", "blend": "multiply", "rect": [0, 0, 1920, 1080], "z": 1, "motion": {"type": "geometric", "zoom": [1.0, 1.05]}},
                {"id": "accent", "type": "code", "draw": "bar", "rect": [0, 880, 240, 70], "color": "#E03A3A", "z": 2, "motion": {"type": "geometric", "pan": [0, 540]}}
            ],
            "gates": [
                {"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0005, "hi": 0.08},
                {"id": "red", "metric": "red_pixel_ratio", "lo": 0.002, "hi": 0.02},
                {"id": "keyPurity", "metric": "edge_key_purity", "lo": 0.98}
            ]
        }
        with open(target, "w") as f:
            json.dump(template, f, indent=2)
        print(f"Initialized new shot specification: {target}")

    elif args.command == "concat":
        timeline_path = os.path.join(ROOT, args.timeline)
        if not os.path.exists(timeline_path):
            os.makedirs(os.path.dirname(timeline_path), exist_ok=True)
            with open(timeline_path, "w") as f:
                json.dump({"id": "full-sequence", "shots": ["spec/shot-01.poster.json"]}, f, indent=2)
            print(f"Created default timeline at: {timeline_path}")

        with open(timeline_path) as f:
            tl = json.load(f)

        shots = tl.get("shots", [])
        if not shots:
            sys.exit("Error: timeline.json has no shots")

        rendered_mp4s = []
        for shot in shots:
            shot_file = os.path.join(ROOT, shot if shot.endswith(".json") else f"spec/{shot}.poster.json")
            if not os.path.exists(shot_file):
                sys.exit(f"Error: shot spec not found: {shot_file}")
            with open(shot_file) as sf:
                s_data = json.load(sf)
            sid = s_data["id"]
            mp4_path = os.path.join(ROOT, "build", f"{sid}.mp4")
            if not os.path.exists(mp4_path):
                print(f"Shot MP4 missing: {mp4_path}. Rendering now...")
                run_stage(["03_compose.py", "--spec", shot_file], f"Render {sid}")
            rendered_mp4s.append(mp4_path)

        out_path = os.path.join(ROOT, args.output)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        concat_txt = os.path.join(ROOT, "build", "concat_list.txt")
        with open(concat_txt, "w") as f:
            for p in rendered_mp4s:
                f.write(f"file '{os.path.abspath(p)}'\n")

        print(f"Concatenating {len(rendered_mp4s)} shots -> {out_path} ...")
        cmd = [
            "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_txt, "-c", "copy", "-movflags", "+faststart", out_path
        ]
        subprocess.run(cmd, check=True)
        print(f"Successfully generated: {out_path} (size: {os.path.getsize(out_path)} bytes)")

    elif args.command == "test":
        run_stage(["-m", "unittest", "discover", "tests"], "Regression Test Suite")

    elif args.command == "clean":
        b_dir = os.path.join(ROOT, "build")
        if os.path.exists(b_dir):
            shutil.rmtree(b_dir)
            print("Removed build/ directory.")
        print("Clean complete.")


if __name__ == "__main__":
    main()
