"""S5: Visual Self-Audit Inspection stage.

Two modes:

1. Evidence generation (default):
   Generates a tiled contact sheet from the rendered shot video and extracts an
   inspection inventory of the spec's declared resources (ai assets, video
   clips, project components) plus the project-declared `spec.checklist`.
   Writes build/contact_sheet_{shot_id}.png
   and build/inspection_{shot_id}.json, and registers a *pending* visual audit
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
import re
import subprocess
import sys

# stages/ lives one level below the repo root; put the root on sys.path so
# `import core.*` works however this script was invoked (direct, -m, or
# importlib).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from core.runtime import manifest
from core.runtime.config import ROOT
from core.spec.loader import load_spec


def extract_checklist(spec):
    """Extract the project-declared resources and checklist.

    The spec's user checklist, when present, must be a non-empty array of
    strings — a typo there is a malformed project, not an absent checklist.
    """
    declared = spec.get("checklist", [])
    if not isinstance(declared, list) or any(not isinstance(item, str) or not item.strip() for item in declared):
        raise ValueError("spec.checklist must be an array of non-empty strings")
    checklist = {"ai_assets": [], "video_assets": [], "components": [],
                 "project_checklist": declared}
    for layer in spec.get("layers", []):
        kind = layer.get("type")
        if kind == "component":
            checklist["components"].append({"id": layer.get("id"), "component": layer.get("component")})
        elif kind in ("ai", "video"):
            entry = {"id": layer.get("id"), "asset": layer.get("asset")}
            if kind == "video":
                row = manifest.verified("prepared", f"{spec['id']}/{layer.get('asset')}") or {}
                for field in ("source_duration", "shot_duration", "upscale"):
                    if row.get(field) is not None:
                        entry[field] = row[field]
            checklist[kind + "_assets"].append(entry)
    return checklist


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
    scale=360:640 squashed any landscape (16:9) shot into a portrait cell. If
    ffprobe cannot determine the dimensions, keep a neutral square cell."""
    if not vw or not vh:
        return (long_side, long_side)
    if vh >= vw:
        return max(1, round(long_side * vw / vh)), long_side
    return long_side, max(1, round(long_side * vh / vw))


def contact_sample_indices(duration_frames, grid):
    """Evenly cover both endpoints; repeat frames for short videos.

    A single cell shows the first frame. duration_frames must match the video;
    otherwise generating the sheet fails rather than silently leaving cells blank.
    """
    if not isinstance(grid, str) or not re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", grid):
        raise ValueError("grid must have positive integer dimensions, e.g. 3x3")
    if isinstance(duration_frames, bool) or not isinstance(duration_frames, int) or duration_frames < 1:
        raise ValueError("duration_frames must be a positive integer")
    cols, rows = map(int, grid.split("x"))
    count = cols * rows
    if count == 1:
        return [0]
    return [(i * (duration_frames - 1) * 2 + count - 1) // (2 * (count - 1))
            for i in range(count)]


def generate_contact_sheet(mp4_path, duration_frames, out_sheet_path, grid="3x3"):
    indices = contact_sample_indices(duration_frames, grid)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", mp4_path],
        capture_output=True, text=True, check=True)
    try:
        actual_frames = int(probe.stdout.strip())
    except ValueError as exc:
        raise ValueError("cannot determine video frame count") from exc
    if actual_frames != duration_frames:
        raise ValueError(f"video has {actual_frames} frames, expected {duration_frames}")
    vw, vh = probe_video_dims(mp4_path)
    cw, ch = contact_sheet_cell(vw, vh)

    os.makedirs(os.path.dirname(out_sheet_path) or ".", exist_ok=True)
    # Each branch selects one frame, so repeated indices fill short-shot grids.
    # Concatenation followed by tile also avoids FFmpeg's partial-sheet padding.
    branches = ''.join(f'[s{i}]' for i in range(len(indices)))
    filters = [f'[0:v]split={len(indices)}{branches}']
    for i, index in enumerate(indices):
        filters.append(f'[s{i}]select=eq(n\\,{index}),setpts=PTS-STARTPTS[f{i}]')
    inputs = ''.join(f'[f{i}]' for i in range(len(indices)))
    filters.append(f'{inputs}concat=n={len(indices)}:v=1:a=0,scale={cw}:{ch},tile={grid}[sheet]')

    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-i", mp4_path,
        "-filter_complex", ';'.join(filters), "-map", "[sheet]",
        "-frames:v", "1",
        out_sheet_path
    ]
    subprocess.run(cmd, check=True)
    return out_sheet_path



def sibling_sheets(shot_id):
    """Contact sheets of other shots in build/ — evidence for the diversity criterion."""
    import glob as _glob
    build = os.path.join(ROOT, "build")
    return sorted(
        os.path.relpath(p, ROOT)
        for p in _glob.glob(os.path.join(build, "contact_sheet_*.png"))
        if os.path.basename(p) != f"contact_sheet_{shot_id}.png"
    )


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
    return (
        f"\n[S5 judge] shot={shot_id}\n  sheet: {sheet_rel}\n"
        f"  project checklist and declared resources: {json.dumps(checklist, ensure_ascii=False)}\n"
        '  record: python3 pipeline.py judge --spec <spec> --verdict pass|fail --notes "..."\n'
    )


def generate(args):
    spec = load_spec(args.spec)
    shot_id = spec.get("id", "shot-01")
    mp4_path = os.path.join(ROOT, "build", f"{shot_id}.mp4")

    if not os.path.exists(mp4_path):
        raise RuntimeError(f"Cannot run S5: Video not found at {mp4_path}. Run S3 first.")

    duration_frames = spec["durationInFrames"]  # required by the schema
    sheet_rel = f"build/contact_sheet_{shot_id}.png"
    sheet_path = os.path.join(ROOT, sheet_rel)

    print(f"Generating {args.grid} contact sheet for {shot_id} -> {sheet_rel} ...")
    generate_contact_sheet(mp4_path, duration_frames, sheet_path, grid=args.grid)

    checklist = extract_checklist(spec)
    total_resources = (len(checklist["ai_assets"]) + len(checklist["video_assets"])
                       + len(checklist["components"]))
    total_checklist_items = len(checklist["project_checklist"])

    inspection_record = {
        "shot_id": shot_id,
        "contact_sheet": sheet_rel,
        "grid": args.grid,
        "durationInFrames": duration_frames,
        "checklist": checklist,
        "total_resources": total_resources,
        "total_checklist_items": total_checklist_items,
        "audit_criteria": spec.get("checklist", []),
        "verdict": "pending_judge",
        "notes": None,
    }

    inspect_json = os.path.join(ROOT, "build", f"inspection_{shot_id}.json")
    with open(inspect_json, "w") as f:
        json.dump(inspection_record, f, indent=2, ensure_ascii=False)

    upsert_gate_entry(shot_id, None, "pending_judge", sheet_rel, total_checklist_items)

    print(f"PENDING visual_inspect contact_sheet_tile  {sheet_rel}  "
          f"[{total_resources} resources, {total_checklist_items} checklist items]")
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
    parser.add_argument("--spec", default=None, help="Path to spec file (required)")
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
