---
name: code-driven-shot-pipeline
description: >-
  Design, synthesize, and verify code-driven short-video knowledge shots.
  5-stage deterministic build (Generate, Prepare, Compose, Gate, Inspect) with
  lockfile manifest, audio mastering + QC gates, a visual-audit judge loop,
  narrative timeline contracts, and a spec-driven expression vocabulary
  (keyframe anim channels, parameterized field/path primitives, decoration
  opt-outs). The pipeline is fixed; every episode designs its own shot layouts.
---

# Code-Driven Shot Pipeline

The pipeline treats video synthesis like software compilation: a structured JSON
spec (`spec/*.poster.json`) compiles deterministically (bit-exact mp4) through 5
decoupled stages with hard quality gates.

**The one design law: the pipeline is fixed, expression lives in the spec.**
Stage flow, manifest authority, and gates never change per episode. Layout,
composition, motion, entrance timing, and atmosphere are authoring decisions
made fresh in every spec. **Never clone a previous episode's skeleton** — a
cloned layout is the single most recognizable failure of this pipeline (identical
badge/title/framed-card/capsule/HUD stack across shots reads as template output).

## The One Design Law, Applied

Design each shot's composition from its narrative role before writing layers.
Three verified composition languages (read them as specs, not as templates to copy):
- **Full-bleed poster (hook)** — `plate: false` AI image covering the whole canvas,
  oversized title in the lower third via `anim` keyframes, a `path` accent stroke,
  `field` particles. See `skills/code-driven-shot-pipeline/references/reference_hook_poster.json`.
- **Pure diagram (development)** — no AI layer at all; dot-grid ground, a physics
  diagram draw, a formula card entering exactly when the narration states it.
  See `skills/code-driven-shot-pipeline/references/reference_development_diagram.json`.
- **Full-bleed documentary (resolution)** — real public-domain footage/stills,
  slow zoom-out reveal, orbit `path` lines, restrained captions.
  See `skills/code-driven-shot-pipeline/references/reference_resolution_documentary.json`.

Vary between them *within* an episode. If two shots in one timeline share the same
skeleton, that is a bug in the authoring, not a style.

### Creative dice (anti-convergence protocol)

LLM authoring drifts toward the layouts it has seen — cloning is the default
failure, and "random" does not fix it by itself. Before writing any spec, roll
one sample from each axis and commit it in writing (the rolled combination goes
into the spec's `_design_hints` so the judge can verify it was honored):

- **composition**: full-bleed poster / diagonal split / centered diagram /
  extreme-crop close-up / negative-space dominated / frame-within-frame
- **palette mood**: dark sci-fi / warm paper light / monochrome + single accent /
  complementary clash / duotone
- **entrance rhythm**: instant presence + slow reveal / staggered cascade /
  everything-static-until-one-motion / late punchline
- **camera**: slow push-in / pull-out reveal / lateral drift / locked-off with
  element-only motion
- **HUD density**: none / one instrument / minimal / info-dense

Two specs sharing four or more rolled values is a re-roll. The dice constrain
*form*, never content — the topic and physics stay in charge.

## Expression Vocabulary (spec-driven, renderer just interpolates)

| Channel | Where | What it controls |
|---|---|---|
| `anim` | any layer | Keyframe channels `x/y/scale/opacity/rotate`; frames strictly increasing; optional ease per keyframe (`linear/in/out/inout`) on the segment END. Entrances, camera moves, exits — all data. |
| `field` (code draw) | `params` | Parameterized particle field: `count, seed, colors, dir, spread, speed, size, glow`. Atmosphere on demand, not baked in. |
| `path` (code draw) | `params` | SVG path with `reveal` (dash draw-on) or `flow` (drifting dashes), `stroke/width/opacity`. Guide lines, orbits, energy tracks. |
| `vibe: false` | spec root | Opts out of the baked vertical ambience (particle rain, scanline, blueprint grid). Bring your own atmosphere via layers. |
| `plate: false` | ai layer | Full-bleed presentation — no card chrome (border/rounding/vignette). |
| `color` | text layer | Solid color + scrim instead of the default white-cyan gradient. |

Hero draws (`trampoline`, `gravity-well`, `blackhole-hero`, `time-dilation`,
`light-cone-tilt`, `spaghettification`, `light-deflection`, `spacetime-waves`,
`tunnel-hero`, `wavefunction-hero`) are **legacy hardcoded scenes**: reuse where the
subject matches, never build new episodes around their fixed layouts, and prefer
composing from primitives + `anim` for new content. (Planned: a `three` layer type
via `@remotion/three` — true 3D scenes, frame-driven for determinism.)

## Core Invariants

1. **Manifest Authority (lockfile)** — AI image APIs have no seed; generated assets
   are frozen in `manifest.json` with SHA256 and reused forever after.
   `spec + manifest -> identical sha256 mp4`.
2. **Zero-dependency pixel & audio metrics** — raw-video byte math, not ffmpeg `geq`.
3. **Fail-fast keying purity & aspect-ratio preservation (S2)** — 8px perimeter purity
   >= 98% before render spend; subregion scaling always preserves aspect ratio.
4. **Broadcast audio** — Edge TTS `zh-CN-YunxiNeural` at +18%, mastering chain
   (highpass/EQ/compand) + `loudnorm` to -16 LUFS; ambient = 4-harmonic drone.
5. **Narrative timeline contract** — structured `beat` + non-empty `reason` per shot;
   talk alone is never completed state, only verified `build/` artifacts count.
6. **Honest gating** — deterministic gates say "not broken"; the S5 judge says
   "looks right and says something". Neither substitutes for the other.

## The 5 Stages + Judge Loop

| Stage | Script | Contract | Exit codes |
|---|---|---|---|
| S1 Generate | `stages/01_generate.py` | Fetch/verify AI assets into `assets/`, record SHA256 in manifest. | 0 / 1 |
| S2 Prepare | `stages/02_prepare.py` | Key purity gate, aspect-true scaling, code backgrounds into `build/prepared/{shot}/`. | 0 / 1 |
| S3 Compose | `stages/03_compose.py` | Remotion render -> `build/frames/{shot}/%05d.png` + `build/{shot}.mp4` (BT.709, mastered audio). | 0 / 1 |
| S4 Gate | `stages/04_gate.py` | Motion/accent/purity/freeze + audio QC (silence > -45 dB, LUFS in [-19,-13], AV sync <= 100 ms) -> `build/gates/{shot}.json`. | 0 / 1 |
| S5 Inspect | `stages/05_inspect.py` | Contact sheet + spec-derived checklist. Verdict is **`pending_judge`** (`pass: null`) — it never claims the shot looks right. | 0 |
| S5+ Judge | `pipeline.py judge --verdict pass\|fail --notes` | A model or human reads the sheet against the checklist and records the verdict; `fail` exits 1 (hard gate). An S4 re-run invalidates a stale verdict. | 0 / 1 |

## Full-Video Gates (concat)

`pipeline.py concat` runs post-assembly checks per-shot gates cannot see, writing
`build/gates_full_{timeline_id}.json` (exit 1 on any red): timeline duration delta
<= 250 ms, zero digital-black intervals, whole-track silence/loudness, AV alignment
<= 250 ms, per-segment loudness jump <= 3 LU.

## Asset Transport (S1)

`stages/01_generate.py` calls the `mcode-tools connector` where available. On
machines without it, keep the manifest contract and substitute the transport:
gradio_client -> HF Spaces (watch for webp bytes masquerading as .png — convert to
true PNG before registering, data-URL MIME is not sniffed by Chromium), or
public-domain sources (NASA SDO etc.) registered with `source=` and `credit=`.
ZeroGPU anonymous quota is tiny and policy-drifts; a free account token is the
reliable channel.

### Native Generation Backends

The connector exposes native image and video generation. The pipeline is the
consumer; these are the backends it can drive.

**Image** — `connector__matrix__generate_image` (text-to-image, plus
image-to-image via `input_urls`). Takes `aspect_ratio` (1:1 / 16:9 / 9:16 /
4:3 / 3:4 / 21:9) and `resolution` (1K / 2K / 4K). S1 derives `aspect_ratio`
from the spec canvas, so a 1080x1920 vertical shot asks for a vertical plate.
The generator may return JPEG/WebP regardless of the requested format — S1
normalizes every download to a true PNG before freezing it.

**Video** — `connector__matrix__submit_video_generation` +
`connector__matrix__query_video_generation`. Asynchronous: submit returns a
`task_id`, the task is polled until it succeeds, then the clip is downloaded
and frozen like any other asset.

| Model | Duration | Resolution | Native audio | Use for |
|---|---|---|---|---|
| `MiniMax-H3` | 4–15s | 768P, 2K | yes | final quality; supports first/last frame + multimodal references (up to 9 images / 3 videos / 3 audios) |
| `MiniMax-H3-Max` | 5–15s | 480P, 768P | yes | fast iteration (~20s); keyframes only |
| `MiniMax-Hailuo-2.3` | 6/10s | 768P, 1080P | no | cheap drafts; silent, needs TTS on top |

**Audio ownership is exclusive.** H3-family clips render a synchronized native
audio track (dialogue, ambience, SFX). The pipeline's own audio chain
(`core/audio.py`) is Edge TTS + ambient drone + `loudnorm` to -16 LUFS. Pick
one as the main track:

- **TTS owns the audio** (default): the video layer is muted
  (`"muted": true`) and the spec's `audio.voiceover` drives the soundtrack.
- **The clip owns the audio**: set `"muted": false` on the video layer and
  leave `audio.voiceover` empty for that shot. The clip's own track is used;
  do not also request TTS for the same shot, or the two will overlap.

Mixing both is a bug, not a style choice — the S4 audio gates (silence, LUFS,
AV sync) will flag it.

## Layer Types

1. **`ai`** — prepared image layer; `blend`, `keyColor`, `motion.zoom`, `fit`, `plate`.
2. **`video`** — prepared video layer; `asset` (an mp4), `fit`, `trim`, `loop`,
   `muted`, `motion.zoom`, `plate`. No `keyColor`: edge keying is a still-image
   concept, so a video layer skips the purity gate and is scaled to cover its
   rect instead. The clip is re-encoded at the shot's frame rate in S2 — a
   source clip at a different rate would otherwise loop over a window longer
   than itself and freeze on its last frame.
3. **`code`** — `grid | dots | bar | field | path` (parameterized primitives) plus
   legacy hero scenes (see vocabulary section).
4. **`text`** — title/subtitle, spring or keyframe entrance, gradient or solid `color`.
5. **`hud`** — `badge | telemetry | equalizer | progress | scanline`. Decorative:
   use deliberately, not by default on every shot.
6. **`card`** — `capsule | formula | quote`.

## Quick Start

```bash
python3 pipeline.py init-shot shot-02                      # schema skeleton + design hints (no layout)
python3 pipeline.py run --spec spec/my-shot.poster.json    # S1->S5 (visual verdict pending)
python3 pipeline.py judge --spec spec/my-shot.poster.json --verdict pass --notes "..."   # close S5
python3 pipeline.py concat --timeline spec/my-timeline.json --output build/full.mp4      # + full-video gates
python3 pipeline.py test                                   # regression suite
```
