# Poster Video Pipeline (Code-Driven Single-Shot)

A deterministic, code-driven video synthesis pipeline that compiles a structured shot specification (`spec/*.poster.json`) into 1080p 30fps video using 3 layers:
1. **Code Background** (Procedural `grid` or `dots`)
2. **AI Subject** (City silhouette, blend: multiply, edge keying)
3. **Code Foreground** (Animated geometric accent `bar`)

AI subject layers may be still images or video clips. The pipeline drives native generation backends through `mcode-tools connector` — see [Native Generation Backends](#native-generation-backends).

---

## Native Generation Backends

The pipeline calls native image and video models through the connector, then
freezes the result into `manifest.json` by sha256 — the same lockfile contract
as any other asset. Once frozen, a clip is reused forever; re-renders stay
bit-exact.

**Images** — `connector__matrix__generate_image` (text-to-image, image-to-image
via `input_urls`). S1 derives the request's aspect ratio from the spec canvas
and normalizes the download to a true PNG before registering it.

**Video** — `connector__matrix__submit_video_generation` +
`connector__matrix__query_video_generation`. Asynchronous: submit returns a
`task_id`, the task is polled until it succeeds, the clip is downloaded and
frozen. A `type: "video"` layer in the spec consumes it.

| Model | Duration | Resolution | Native audio |
|---|---|---|---|
| `MiniMax-H3` | 4–15s | 768P, 2K | yes |
| `MiniMax-H3-Max` | 5–15s | 480P, 768P | yes (~20s turnaround) |
| `MiniMax-Hailuo-2.3` | 6/10s | 768P, 1080P | no |

A video layer renders through Remotion's `Video` component; the clip is scaled
to cover its rect and re-encoded at the shot's frame rate in S2. Audio
ownership is exclusive — either the clip's native track or the pipeline's TTS
chain is the main track, never both (see the Skill's "Audio ownership" rule).

---

## Architecture & Stages

```
spec/*.json ───► [ S1: Generate ] ───► assets/*.png | *.mp4 ───► (manifest lockfile)
                         │
                         ▼
                 [ S2: Prepare  ] ───► build/prepared/{shot}/*.png | *.mp4 (Fail-fast: key purity >= 0.98; video layers skip keying)
                         │
                         ▼
                 [ S3: Compose  ] ───► build/frames/{shot}/*.png + build/*.mp4 (Remotion render engine)
                         │
                         ▼
                 [ S4: Gate     ] ───► build/gates/{shot}.json (Zero-dependency rawvideo pixel metrics + audio QC)
                         │
                         ▼
                 [ S5: Inspect  ] ───► build/contact_sheet_{shot}.png + build/inspection_{shot}.json (verdict pending judge)
```

| Stage | Command / Script | Inputs | Outputs | Exit Code Contract |
|---|---|---|---|---|
| **S1** | `stages/01_generate.py` | `spec/`, `manifest.json` | `assets/*.png`, `manifest.json` | `0` = Assets ready & verified; `1` = Error |
| **S2** | `stages/02_prepare.py` | `assets/`, `spec/` | `build/prepared/{shot}/*.png` | `0` = Scaled & pure; `1` = Blocked by key purity `< 0.98` |
| **S3** | `stages/03_compose.py` (Remotion) | `build/prepared/{shot}/`, `spec/` | `build/frames/{shot}/%05d.png`, `build/*.mp4` | `0` = 150 frames & MP4 encoded |
| **S4** | `stages/04_gate.py` | `build/frames/{shot}/`, `build/*.mp4` | `build/gates/{shot}.json` | `0` = All gates pass; `1` = Quality violation |
| **S5** | `stages/05_inspect.py` | `build/{shot}.mp4`, `spec/` | `build/contact_sheet_{shot}.png`, `build/inspection_{shot}.json` | `0` = Evidence generated (verdict `pending_judge`) |
| **S5+** | `pipeline.py judge --verdict pass\|fail` | contact sheet + checklist | verdict in `inspection_{shot}.json` + `build/gates/{shot}.json` | `0` = judged pass; `1` = judged fail |

S5 splits evidence from verdict: the pipeline never claims a shot *looks* right — a judge (model or human) reads the contact sheet against the spec-declared checklist and records the verdict, which then becomes a hard gate. Prepared artifacts are namespaced per shot (`build/prepared/{shot_id}/`) so a shared `bg` layer can no longer let one shot's style silently overwrite another's.

---

## Core Invariants

1. **Manifest Authority (Lockfile Pattern)**:
   AI asset generation is non-reentrant (no seed parameter). Once generated, assets are recorded in `manifest.json` with their `sha256` checksum. Subsequent runs strictly reuse verified assets, ensuring bit-for-bit reproducibility of the final MP4 (`spec + manifest -> identical sha256`).
2. **Zero-Dependency Pixel Metrics**:
   Bypasses unstable FFmpeg `geq` filter expressions. Uses `ffmpeg -f rawvideo -> Python stdlib` with bit-twiddling (`bytes.translate`, `int.from_bytes`, and `bit_count` popcounts) for lightning-fast and resolution-independent pixel analysis.
3. **Fail-Fast Keying Purity**:
   Outer 8px perimeter is measured before composition. Impure backgrounds are rejected at S2 before spending compute on composition.

---

## Quality Gates

| Gate | Metric | Definition | Threshold |
|---|---|---|---|
| `motion` | `changed_pixel_ratio` | Median fraction of pixels with Luma $\Delta > 6$ | `[0.0005, 0.08]` |
| `subject` | `subject_motion_ratio` | Median fraction of pixels with Luma $\Delta > 6$ excluding bar region | `[0.0005, 0.08]` |
| `red` | `red_pixel_ratio` | Median fraction of red accent mask pixels | `[0.002, 0.02]` |
| `accent` | `accent_color_ratio` | Median fraction of accent color mask pixels | `[0.002, 0.02]` |
| `keyPurity` | `edge_key_purity` | Fraction of outer 8px border matching key color within tolerance | `≥ 0.98` |
| `freeze` | `freezedetect` | Unintended frozen segments | `0` segments |

---

## Quick Start

### 1. Prerequisites
- `ffmpeg` (version >= 5.0 recommended, with `x264`, `freezedetect`)
- `python3` (version >= 3.10, standard library only)
- `node` (version >= 18.0) and `npm` (run `npm install` for Remotion dependencies)
- `mcode-tools` — the CLI the native generation backends are driven through
  (image: `connector__matrix__generate_image`; video:
  `connector__matrix__submit_video_generation`). Without it the pipeline can
  still run end to end on assets you register yourself — see
  [Native Generation Backends](#native-generation-backends).

### 2. Verify and Test
```bash
make verify
# or
python3 pipeline.py test
```

### 3. Initialize a New Shot
```bash
python3 pipeline.py init-shot my-shot
```

### 4. Run Pipeline
```bash
# Rehearse the whole pipeline for free first: --fixture writes deterministic
# placeholder assets instead of calling a (billed) model. The placeholders
# are registered in the ledger, so a later real run reuses them — pass
# --force to S1 when you want the generated asset instead.
python3 pipeline.py run --spec spec/my-shot.poster.json --fixture

# Full execution (validate -> S1 -> S2 -> S3 -> S4 -> S5)
make run
# or
python3 pipeline.py run --spec spec/my-shot.poster.json

# Judge the contact sheet after review (closes the S5 loop)
python3 pipeline.py judge --spec spec/my-shot.poster.json --verdict pass --notes "..."

# Clean build artifacts
make clean
```

#### Using a generated video clip

A spec layer of `"type": "video"` pulls in a generated clip:

```json
{
  "id": "hero-clip",
  "type": "video",
  "asset": "h3-push-in",
  "rect": [0, 0, 1080, 1920],
  "z": 0,
  "plate": false,
  "model": "MiniMax-H3-Max",
  "duration": 6,
  "muted": true
}
```

```bash
python3 pipeline.py run --spec spec/my-shot.poster.json
```

S1 submits the clip, polls until the model finishes, downloads it and freezes
it by sha256 — this is the slow, billed step (`MiniMax-H3-Max` ~20s,
`MiniMax-H3` 15–30 min). Later runs reuse the frozen clip. `model`,
`duration`, `resolution` and `ratio` are validated before the call, so a typo
is rejected by `validate` rather than by a paid request. `muted` decides who
owns the audio: `true` (default) leaves the clip silent and the spec's
`audio.voiceover` owns the soundtrack; `false` keeps the clip's native track
and `audio.voiceover` must then be left empty for that shot. A timeline whose
shots disagree on that is refused by `concat`, because the concat demuxer
would silently drop every audio track.

**Time window.** Without `trim`, the renderer takes the clip from its start: a
clip longer than the shot is cut at the shot's length, a shorter one loops.
`trim: [startSec, endSec]` selects a window instead; the seconds are read at
the shot's frame rate, since S2 re-encodes every clip to that rate.

#### Image-to-image

An `ai` layer can derive from an already-frozen asset:

```json
{
  "id": "hero-plate",
  "type": "ai",
  "asset": "snowy-skyline",
  "input_asset": "my-base-asset",
  "prompt": "a snowy version of the same skyline, cold blue light",
  "keyColor": "#ffffff",
  "blend": "multiply",
  "rect": [0, 0, 1080, 1920],
  "z": 0
}
```

`input_asset` names a manifest asset. S1 uploads it, passes the temporary URL
to the backend and freezes the derived image like any other asset. A layer's
`prompt` replaces the style's `subject`/`composition`; `background` and
`exclude` still apply as global constraints.

### 5. Concatenate Shots via Timeline
```bash
python3 pipeline.py concat --timeline spec/timeline.json --output build/my-film.mp4
```
Concat also runs **full-video gates** on the assembled output (duration vs timeline, blackdetect, whole-track silence/loudness, A/V alignment, per-shot loudness jump ≤3 LU), written per timeline to `build/gates_full_{timeline}.json`; exit 1 on any red. Per-shot gates cannot see cross-shot seams — this is the layer that does.

---

## Repository Layout

This repository is the **engine** (the skill). It contains no shot specs or
generated assets — those live in a **project** directory (e.g. an examples
repo) that the engine renders. Point the pipeline at a project with
`POSTER_ROOT`:

```bash
cd /path/to/my-project          # contains spec/, assets/, manifest.json
POSTER_ROOT=$PWD python3 /path/to/poster-pipeline/pipeline.py run --spec spec/my-shot.poster.json
```

```
pipeline.py            Unified CLI: validate / generate / prepare / compose / gate / inspect / judge / run / concat / test
stages/                One script per stage: 01_generate … 05_inspect
core/                  Shared runtime: schema (spec contract), manifest (frozen-file ledger),
                       metrics (pixel QC), audio (TTS + mastering), render (frame & encoder fingerprints),
                       draw / png (procedural layers), rig (sprite rigging & IK)
remotion/              TypeScript renderer (React) — the S3 render engine
tests/                 Regression suite (make verify); fixtures live in tests/fixtures/
skills/                The packaged Agent Skill (skills/code-driven-shot-pipeline/)
```

A project directory holds `spec/` (shot specs, styles, timelines), `assets/`
(frozen AI-generated images, sha256 in `manifest.json`), `build/` (outputs),
and optionally `remotion-custom.tsx` (project-specific custom components,
aliased in as the `project-custom` module — see `remotion.config.ts`).

Run a stage directly when debugging it:
```bash
python3 stages/03_compose.py --spec spec/my-shot.poster.json
```

---

## Reusable Agent Skill

This pipeline is packaged as a reusable Agent Skill located at:
- Repository source: `skills/code-driven-shot-pipeline/`
- Installed agent skill: `/Users/kelen/.agents/skills/code-driven-shot-pipeline/`
