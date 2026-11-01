"""S5: Visual Self-Audit Inspection stage.

Two modes:

1. Evidence generation (default):
   Generates a tiled contact sheet from the rendered shot video and extracts an
   inspection checklist against the spec's declared layers (texts, cards, AI
   assets, draw types, HUD). Writes build/contact_sheet_{shot_id}.png and
   build/inspection_{shot_id}.json, and registers a *pending* visual audit
   entry in build/gates/{shot_id}.json (pass=null, status=pending_judge). Nothing here
   claims the shot looks right — that verdict belongs to a judge (model or
   human) reading the sheet, recorded via --record.

2. Verdict recording (--record pass|fail):
   Writes the judge's verdict + notes into build/inspection_{shot_id}.json and
   flips the gates.json visual_inspect entry to a real pass/fail. A fail exit
   code (1) makes the visual audit a hard gate, same contract as S4.

Usage:
  python3 05_inspect.py [--spec path/to/spec.json] [--grid 3x3]
  python3 05_inspect.py --spec path/to/spec.json --record pass --notes "..."
  python3 05_inspect.py --spec path/to/spec.json --record fail --notes "..."
"""
import argparse
import json
import os
import subprocess
import sys

from schema import ROOT, load_spec


def extract_checklist(spec):
    texts = []
    cards = []
    ai_assets = []
    code_draws = []
    hud_types = []

    for layer in spec.get("layers", []):
        ltype = layer.get("type")
        if ltype == "text":
            if layer.get("text"):
                texts.append({"id": layer.get("id"), "text": layer.get("text"), "subtext": layer.get("subtext")})
        elif ltype == "card":
            cards.append({
                "id": layer.get("id"),
                "cardType": layer.get("cardType"),
                "title": layer.get("title"),
                "quote": layer.get("quote")
            })
        elif ltype == "ai":
            ai_assets.append({"id": layer.get("id"), "asset": layer.get("asset")})
        elif ltype == "code":
            code_draws.append({"id": layer.get("id"), "draw": layer.get("draw")})
        elif ltype == "hud":
            hud_types.append({"id": layer.get("id"), "hudType": layer.get("hudType")})

    return {
        "texts": texts,
        "cards": cards,
        "ai_assets": ai_assets,
        "code_draws": code_draws,
        "hud_types": hud_types
    }


def probe_video_dims(mp4_path):
    """Video stream width/height via ffprobe; (0, 0) if unreadable."""
    import re
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", mp4_path],
        capture_output=True, text=True)
    m = re.search(r"(\d+),(\d+)", res.stdout or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def contact_sheet_cell(vw, vh, long_side=640):
    """Tile cell size that preserves the video's aspect ratio. The old hardcoded
    scale=360:640 squashed any landscape (16:9) shot into a portrait cell."""
    if not vw or not vh:
        return 360, 640  # probe failed: keep the historical portrait default
    if vh >= vw:
        return round(long_side * vw / vh), long_side
    return long_side, round(long_side * vh / vw)


def generate_contact_sheet(mp4_path, duration_frames, out_sheet_path, grid="3x3"):
    cols, rows = map(int, grid.split("x"))
    total_samples = cols * rows
    step = max(1, duration_frames // total_samples)

    vw, vh = probe_video_dims(mp4_path)
    cw, ch = contact_sheet_cell(vw, vh)

    os.makedirs(os.path.dirname(out_sheet_path), exist_ok=True)
    vf = f"select='not(mod(n\\,{step}))',scale={cw}:{ch},tile={grid}"

    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-i", mp4_path,
        "-vf", vf,
        "-frames:v", "1",
        out_sheet_path
    ]
    subprocess.run(cmd, check=True)
    return out_sheet_path


AUDIT_CRITERIA = [
    "text_legibility: All title/subtitle/quote texts readable without character corruption or overlap",
    "subject_fidelity: Visual subject matches declared AI asset or Code draw type without stretch",
    "motion_coherence: Motion animates smoothly and logically across contact sheet frames",
]


def upsert_gate_entry(shot_id, pass_, status, sheet_rel, checklist_items, notes=None):
    """Insert/replace the visual_inspect row in build/gates/{shot_id}.json (if
    S4 has produced the file). Each shot owns its gates file, so a stale judged
    entry cannot leak into another shot's verdicts; an S4 re-run still rewrites
    this file, so a stale judged entry cannot survive a re-render either."""
    gates_path = os.path.join(ROOT, "build", "gates", f"{shot_id}.json")
    if not os.path.exists(gates_path):
        return
    with open(gates_path) as f:
        gates = json.load(f)
    gates = [g for g in gates if g.get("id") != "visual_inspect"]
    entry = {
        "id": "visual_inspect",
        "metric": "contact_sheet_tile",
        "value": sheet_rel,
        "checklist_items": checklist_items,
        "pass": pass_,
        "status": status,
    }
    if notes:
        entry["notes"] = notes
    gates.append(entry)
    with open(gates_path, "w") as f:
        json.dump(gates, f, indent=2)


def judge_instructions(shot_id, sheet_rel, checklist):
    """The prompt a driving agent (or human) consumes to judge the sheet."""
    items = {k: [e.get("text") or e.get("title") or e.get("asset") or e.get("draw") or e.get("hudType") or e.get("id") for e in v]
             for k, v in checklist.items()}
    return (
        f"\n[S5 judge] shot={shot_id}\n"
        f"  sheet: {sheet_rel}\n"
        f"  declared elements: {json.dumps(items, ensure_ascii=False)}\n"
        f"  criteria:\n"
        + "".join(f"    - {c}\n" for c in AUDIT_CRITERIA) +
        f"  record: python3 pipeline.py judge --spec <spec> --verdict pass|fail --notes \"...\"\n"
    )


def generate(args):
    spec = load_spec(args.spec)
    shot_id = spec.get("id", "shot-01")
    mp4_path = os.path.join(ROOT, "build", f"{shot_id}.mp4")

    if not os.path.exists(mp4_path):
        raise RuntimeError(f"Cannot run S5: Video not found at {mp4_path}. Run S3 first.")

    duration_frames = spec.get("durationInFrames", 150)
    sheet_rel = f"build/contact_sheet_{shot_id}.png"
    sheet_path = os.path.join(ROOT, sheet_rel)

    print(f"Generating {args.grid} contact sheet for {shot_id} -> {sheet_rel} ...")
    generate_contact_sheet(mp4_path, duration_frames, sheet_path, grid=args.grid)

    checklist = extract_checklist(spec)
    total_items = sum(len(v) for v in checklist.values())

    inspection_record = {
        "shot_id": shot_id,
        "contact_sheet": sheet_rel,
        "grid": args.grid,
        "durationInFrames": duration_frames,
        "checklist": checklist,
        "total_checklist_items": total_items,
        "audit_criteria": AUDIT_CRITERIA,
        "verdict": "pending_judge",
        "notes": None,
    }

    inspect_json = os.path.join(ROOT, "build", f"inspection_{shot_id}.json")
    with open(inspect_json, "w") as f:
        json.dump(inspection_record, f, indent=2, ensure_ascii=False)

    upsert_gate_entry(shot_id, None, "pending_judge", sheet_rel, total_items)

    print(f"PENDING visual_inspect contact_sheet_tile  {sheet_rel}  [{total_items} checklist items]")
    print(judge_instructions(shot_id, sheet_rel, checklist))
    return 0


def record(args):
    spec = load_spec(args.spec)
    shot_id = spec.get("id", "shot-01")
    inspect_json = os.path.join(ROOT, "build", f"inspection_{shot_id}.json")
    if not os.path.exists(inspect_json):
        raise RuntimeError(
            f"No inspection record for {shot_id}; run S5 (05_inspect.py) first")
    with open(inspect_json) as f:
        record_data = json.load(f)

    record_data["verdict"] = args.record
    record_data["notes"] = args.notes
    with open(inspect_json, "w") as f:
        json.dump(record_data, f, indent=2, ensure_ascii=False)

    upsert_gate_entry(shot_id, args.record == "pass", "judged",
                      record_data.get("contact_sheet", ""),
                      record_data.get("total_checklist_items", 0),
                      notes=args.notes)

    label = "PASS" if args.record == "pass" else "FAIL"
    print(f"{label}  visual_inspect judge_verdict       {record_data.get('contact_sheet', '')}")
    if args.notes:
        print(f"       notes: {args.notes}")
    return 0 if args.record == "pass" else 1


def main():
    parser = argparse.ArgumentParser(description="S5: Visual Self-Audit Inspection")
    parser.add_argument("--spec", default=None, help="Path to spec file (default: spec/shot-01.poster.json)")
    parser.add_argument("--grid", default="3x3", help="Contact sheet grid layout (default: 3x3)")
    parser.add_argument("--record", choices=["pass", "fail"], default=None,
                        help="Record a judge verdict instead of generating evidence")
    parser.add_argument("--notes", default=None, help="Judge findings to store with the verdict")
    args = parser.parse_args()

    if args.record:
        return record(args)
    return generate(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        print(f"S5 ERROR: {ex}", file=sys.stderr)
        sys.exit(1)
