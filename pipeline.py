#!/usr/bin/env python3
"""Unified CLI runner for the code-driven poster video pipeline.
Commands:
  validate   Check spec against schema
  generate   S1: fetch/verify AI assets into manifest
  prepare    S2: key purity gate & scaling & code layers
  compose    S3: single-command ffmpeg composition
  gate       S4: run quality gates (motion, color, purity, freeze)
  run        Execute stages S1 -> S2 -> S3 -> S4 in sequence
  test       Execute full automated test suite
  clean      Clean intermediate build artifacts
"""
import argparse
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

    # test
    subparsers.add_parser("test", help="Run full regression test suite")

    # clean
    subparsers.add_parser("clean", help="Clean build artifacts")

    args = parser.parse_args()

    if args.command == "validate":
        run_stage(["schema.py", args.spec], "Spec Validation")

    elif args.command == "generate":
        gen_args = ["01_generate.py"]
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
        gen_args = ["01_generate.py"]
        if args.force:
            gen_args.append("--force")
        if args.fixture:
            gen_args.append("--fixture")
        run_stage(gen_args, "S1: Asset Generation / Verification")
        run_stage(["02_prepare.py", "--spec", args.spec], "S2: Prepare & Purity Check")
        run_stage(["03_compose.py", "--spec", args.spec], "S3: Compose (FFmpeg)")
        run_stage(["04_gate.py", "--spec", args.spec], "S4: Quality Gates")
        print("\nPipeline completed successfully! All gates passed.")

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
