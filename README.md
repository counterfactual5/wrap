# wrap — Zero-Template Video Pipeline

A deterministic, code-driven video synthesis pipeline. A structured shot
specification (`spec/*.poster.json`) compiles through 5 decoupled stages
into a gated 1080p video.

**The engine ships no design.** No palettes, no built-in components, no
preset scenes, no preset audio, no placeholder assets, no built-in model
catalog. It provides:

- **Asset production** — the authoring LLM inspects currently available tools
  (MCP tools, CLI commands) and decides the modality. If image/video tools exist,
  the LLM uses them (directly or via project `models.json` / env vars); if no
  generation tools exist in the session, the LLM authors procedural `component`
  layers or reuses frozen manifest assets (which needs no model at all).
- **Generic media compositing** — three layer types: `ai` (generated/frozen
  still), `video` (generated/frozen clip), `component` (the project's own
  React component), plus geometric choreography: keyframes, 2D parenting,
  springs, camera zoom, clip timing.
- **Broadcast audio** — optional TTS voiceover (mastered to −16 LUFS),
  explicit-file music, or a compliant silent track.
- **Deterministic verification** — zero-dependency pixel/audio metrics,
  quality gates, contact-sheet judge loop.

Everything visual is authored per video in the project's own components
(`<project>/remotion-custom.tsx`, see below) and generated assets. Old
vocabulary (`code` draws, `text`/`hud`/`card` layers, palettes, `vibe`/
`plate`/`punches`, `gait`/`depth` presets, BGM presets, `--fixture`)
validates to an explicit `migration required` error — it never renders
silently.

---

## Architecture & Stages

```
spec/*.json ───► [ S1: Generate ] ───► assets/*.png | *.mp4 ───► (manifest lockfile)
                         │
                         ▼
                 [ S2: Prepare  ] ───► build/prepared/{shot}/*.png | *.mp4 (fail-fast key purity ≥ 0.98; clips re-encoded to shot fps)
                         │
                         ▼
                 [ S3: Compose  ] ───► build/frames/{shot}/*.png + build/{shot}.mp4 (Remotion render engine)
                         │
                         ▼
                 [ S4: Gate     ] ───► build/gates/{shot}.json (zero-dependency rawvideo pixel metrics + audio QC)
                         │
                         ▼
                 [ S5: Inspect  ] ───► build/contact_sheet_{shot}.png + build/inspection_{shot}.json (verdict pending judge)
```

| Stage | Script | Contract | Exit |
|---|---|---|---|
| **S1** | `stages/01_generate.py` | Fetch/generate assets into `assets/`, freeze sha256; generation parameters validated against declared capabilities *before* the call | `0` / `1` |
| **S2** | `stages/02_prepare.py` | Key purity ≥ 0.98, aspect-true scaling, clip re-encode to shot fps → `build/prepared/{shot}/` (`2` = hard error: unverified asset / still-as-clip) | `0` / `1` / `2` |
| **S3** | `stages/03_compose.py` | Remotion render → frames + mp4 (BT.709, mastered audio); renderer failures are hard errors with the renderer's own output | `0` / `1` |
| **S4** | `stages/04_gate.py` | Motion/accent/purity/freeze + audio QC (LUFS in [−19, −13], AV sync ≤ 100 ms); color gates must declare their `color` explicitly | `0` / `1` |
| **S5** | `stages/05_inspect.py` | Contact sheet + project-declared checklist; verdict `pending_judge` | `0` |
| **S5+** | `pipeline.py judge` | Judge (model or human) records the verdict; `fail` is a hard gate | `0` / `1` |

S5 splits evidence from verdict: the pipeline never claims a shot *looks*
right — a judge reads the contact sheet against the spec's checklist.

### Layer vocabulary (the whole of it)

- **`ai`** — a still image: `asset`, generation `prompt`/`input_asset`/
  `reference_images`, `keyColor`+`blend` keying, `cutout`, `poses`
  (frame-switched sprite swaps), `motion.zoom`, `fit`.
- **`video`** — a clip: `asset`, generation `model`/`duration`/
  `resolution`/`first_frame`/`last_frame`/`reference_images`, `trim`,
  `playbackRate`, `loop`, `muted`, `fit`, `motion.zoom`.
- **`component`** — a project-registered React component: `component` name +
  opaque `props`. The component owns its positioning and every visual
  choice; the engine throws on an unregistered name or missing media.

**Shared:** `z` (unique stacking), `anim` keyframes (`x/y/scale/opacity/rotate/
flipX` + per-segment ease), `parent`/`pivot`/`joint`/`socket` (2D skeletal
parenting), `spring` (`omega`/`zeta`/`coupling`/`channel`/`driverChannel`/`maxAccel` — **all required**), `clipRect`, `flipX`.

**Freeze/black opt-outs:** a shot spec can declare `frame_freeze: true` to permit
frozen frames; a timeline can declare `allow_black: true` to permit intentional
black frames. Use them only when intent is real.

**`spec.tracks`** is non-visual time data: `captions` (subtitle timings,
rendered by project components), `events` (beats/contacts consumed by
`verify-combat` and components), and arbitrary project-defined named timing
tracks (same shape: ordered non-decreasing `frame` ints; `captions` strictly
increasing). No track carries visual semantics.

### Modality & Generation: The LLM Decides From Available Tools

`core/generation/models.py` starts **empty** and ships no built-in models.
**The authoring LLM inspects its current tools and makes the decision:**

1. **Tool Inspection**: The LLM checks available agent/MCP tools in the session
   or terminal CLIs (`which mcode-tools`).
2. **Modality Choice**:
   - If image/video tools exist: the LLM chooses models and parameters from what
     the tools support.
   - If no generation tools exist: the LLM creates procedural React `component`
     layers (100% deterministic, zero cost) or reuses frozen assets.
3. **Capabilities Configuration**:
   Capabilities can be provided via project `models.json` (`POSTER_ROOT/models.json`
   or `spec/models.json`) or environment variables:

| Source | Carries |
|---|---|
| `models.json` or `POSTER_MODELS_JSON` | video models: `min_dur`/`max_dur`, `resolutions`, optional `durations`, `ratios`, `reference_types`, `audio`/`input_image`/`last_frame`/`reference_media` |
| `models.json` or `POSTER_IMAGE_CAPABILITIES_JSON` | image models: `aspect_ratios`, `areas` |
| `models.json` or `POSTER_VIDEO_MODEL` / `POSTER_IMAGE_MODEL` | default model (single candidate auto-defaults) |
| `POSTER_IMAGE_AREA` | default image size tier |

Resolution ladder: explicit layer parameter > project/env default > the
model's single declared value > explicit error (before any paid call).
The `mcode-tools` connector is a transport adapter. Shots that reuse frozen
assets, or carry no generation at all, run with zero capabilities.

### Audio

**Default is silent.** No `audio` block means a compliant 44100 Hz silent
track is produced (S4 exempts it by design). Add audio ONLY when deliberately
desired: `audio.voiceover` (optional TTS; requires an explicit `voice` — no
default narrator is provided), `audio.bgm`
(**explicit file path only** — no presets, a missing file errors), or an
unmuted clip track; mixing TTS/BGM and an unmuted clip in one shot is refused
at validate/S3 ("audio conflict"). Never invent music with code just because
it is possible. `sync-audio` warps
`durationInFrames`, `tracks.captions` and every layer's keyframes to the
TTS clause boundaries. At most one video layer may set `muted: false`.
S4 measures the output to check that an intentionally silent shot is actually
silent. A timeline BGM may cover silent shots only with explicit
`allow_bgm_override_silent: true`.

Before using a trusted existing BGM or voiceover file, register it from the
engine root: `POSTER_ROOT=/path/to/project python3 -m core.audio.integrity register /path/to/audio.wav`.
The manifest checks its SHA-256 before use, including timeline BGM. Existing
projects must register their audio files; changed or unregistered bytes fail
rather than being silently trusted. TTS cache audio and timing metadata are
also verified; legacy cache files require explicit registration or removal
along with their ledger entries before regeneration.

---

## Quality Gates

Gates are declarative in the spec (`spec.gates`); S4 measures them on the
ungraded frames.

| Metric | Definition |
|---|---|
| `changed_pixel_ratio` | median fraction of pixels with Luma Δ > threshold |
| `subject_motion_ratio` | same, excluding a declared region |
| `accent_color_ratio` / `red_pixel_ratio` | mask fraction — the gate must declare its `color` explicitly |
| `edge_key_purity` | outer 8px border matching the key color (≥ 0.98, S2 fail-fast) |
| `freezedetect` | unintended frozen segments = 0 |

Audio QC: silence floor > −45 dB, LUFS in [−19, −13] (BGM-only shots land
at exactly −16.0; mixed voiceover+bgm in [−16, −15]; silent shots ~ −91 dB),
AV sync ≤ 100 ms.

`concat` adds whole-film gates the per-shot pass cannot see: timeline
duration delta ≤ 250 ms, zero digital-black intervals, whole-track
silence/loudness, AV alignment ≤ 250 ms, per-segment loudness jump ≤ 3 LU.

---

## Quick Start

### Prerequisites

- `ffmpeg` (≥ 5.0, with `x264`, `freezedetect`)
- `python3` ≥ 3.10 (the engine uses `int.bit_count()`; `make` auto-detects
  `python3.13→3.12→3.11→3.10`; pin with `make PY=python3.12 verify`)
- `node` (≥ 18) + `npm install` for the Remotion engine
- `mcode-tools` connector — **only** for shots that generate assets;
  register your own assets (or reuse frozen ones) to run without it
- A **dot-free** project path (`POSTER_ROOT`) — Remotion's image-sequence CLI
  rejects any dot anywhere in the output path ("output directory … cannot have
  an extension"); the engine now preflights this and fails before rendering
  with an actionable message. Use `my-project`, not `my.project`.

### Run

```bash
make verify                       # regression suite (offline, no billed calls)

# a zero-design skeleton — canvas/fps/frames are explicit, layers start empty
python3 pipeline.py init-shot my-shot --canvas 1080 1920 --fps 30 --frames 450

python3 pipeline.py run --spec spec/my-shot.poster.json
python3 pipeline.py judge --spec spec/my-shot.poster.json --verdict pass --notes "..."
python3 pipeline.py run --timeline spec/timeline.json --output build/film.mp4
```

#### A generated clip (when the environment declares video capability)

```json
{"id": "hero-clip", "type": "video", "asset": "push-in",
 "rect": [0, 0, 1080, 1920], "z": 0,
 "model": "<declared-model>", "duration": 6, "muted": true}
```

S1 submits (validated against declared capabilities *before* the paid
call), polls, downloads, and freezes the clip by sha256. Later runs reuse
the frozen clip — no regeneration unless `--force`. Discrete-acceptance
backends are honored: `validate` rejects a duration the backend would
refuse, and S1 rounds the shot length up to an accepted value.

#### A generated still

```json
{"id": "hero-plate", "type": "ai", "asset": "skyline",
 "prompt": "...", "keyColor": "#ffffff", "blend": "multiply",
 "rect": [0, 0, 1080, 1920], "z": 0}
```

`input_asset` / `reference_images` name frozen assets for image-to-image
fusion. S1 normalizes every download to a true PNG before freezing.

---

## Repository Layout

This repository is the **engine** (and its packaged skill). It contains no
shot specs or generated assets — those live in a **project** directory
pointed at with `POSTER_ROOT`:

```bash
cd /path/to/my-project        # contains spec/, assets/, manifest.json, remotion-custom.tsx
POSTER_ROOT=$PWD python3 /path/to/wrap/pipeline.py run --spec spec/my-shot.poster.json
```

```
pipeline.py            Unified CLI: validate / generate / prepare / compose / gate /
                       inspect / judge / run / concat / extract-frame / init-shot /
                       sync-audio / verify-* / detect-punches / test / clean
core/
  runtime/             Engine/project roots and the frozen-asset ledger (manifest.json)
  spec/                Contract vocabulary + shot/layer/timeline validation, joint
                       resolution, state handoff
  generation/          S1 transport: connector calls, image/video submit & poll, uploads
  rendering/           S3: Remotion driver (the only render engine), timeline parity,
                       frame extraction, mp4 encode (BT.709, mastered audio)
  assembly/            Timeline assembly domain logic (no argparse / sys.exit)
  media/               PNG IO, fingerprints, canvas geometry
  quality/             Zero-dependency pixel measurements
  audio/               TTS, mastering, caption timing, shot mixing, sync, audio metrics
  rig/                 Sprite processing, kits, poses, kinematics, geometric verification
stages/                S1–S5 stage entry points
remotion/              TypeScript render engine (React/Remotion): bare canvas + the
                       three layer types + project-component registry (project-custom alias)
tests/                 Regression suite (make verify), grouped by target:
                       contract/ (spec contract vs renderer, both directions,
                       migration rejections), core/, stages/, pipeline/, renderer/
                       fixtures + helpers live in tests/ — never in the production path
skills/wrap/           The packaged Agent Skill: SKILL.md (contract + map) and
                       references/ (orchestration, pitfalls, example, design-craft)
```

A project directory holds `spec/` (shot specs, timelines, checklists),
`assets/` (frozen media, sha256 in `manifest.json`), `build/` (outputs), and
`remotion-custom.tsx` — its own visual components, exported as
`CUSTOM_COMPONENTS` and aliased in by `remotion.config.ts` as `project-custom`
when `POSTER_ROOT` points at the project. **Author these components per
video; the engine ships none.**

Run a stage directly when debugging it:

```bash
python3 stages/03_compose.py --spec spec/my-shot.poster.json
```

## Reusable Agent Skill

Packaged at `skills/wrap/` (installed as a symlink at
`~/.agents/skills/wrap`). It carries the operating manual: the zero-template
contract, the layer/tracks protocol, the generation capability schema, audio
rules, stage table, timelines, rigging, and the measured authoring
pitfalls.
