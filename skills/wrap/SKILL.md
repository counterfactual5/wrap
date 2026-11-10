---
name: wrap
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
  `field` particles.
- **Pure diagram (development)** — no AI layer at all; dot-grid ground, a physics
  diagram draw, a formula card entering exactly when the narration states it.
- **Full-bleed documentary (resolution)** — real public-domain footage/stills,
  slow zoom-out reveal, orbit `path` lines, restrained captions.

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
| `captions` (code draw) | `params` | Subtitle track: `items` = list of `{frame, text, hl?, size?}` — each appears from its own `frame` onward; `hl` marks the substring to highlight; `size` (px) and `hlColor` set the styling. No `items` = no subtitles. |
| `vibe: false` | spec root | Opts out of the baked vertical ambience (particle rain, scanline, blueprint grid). Bring your own atmosphere via layers. |
| `plate: false` | ai layer | Full-bleed presentation — no card chrome (border/rounding/vignette). |
| `color` | text layer | Solid color + scrim instead of the default white-cyan gradient. |
| `fontSize` / `fontWeight` / `subtext` | text layer | Title size (px), weight (`string` or number), and the smaller line under the title. |
| `playbackRate` | video layer | Clip speed multiplier (positive number). `1` is real time; `0.5` is half speed. The clip's own audio is not time-stretched to match. |
| `cardType` / `hudType` | card / hud layer | Which card or instrument to draw: card `capsule \| formula \| quote`, hud `badge \| telemetry \| equalizer \| progress`. |
| `details` | card layer | Rows under a formula card: a list of `{label, desc, color?}`. |

Hero draws (`trampoline`, `gravity-well`, `blackhole-hero`, `time-dilation`,
`light-cone-tilt`, `spaghettification`, `light-deflection`, `spacetime-waves`,
`tunnel-hero`, `wavefunction-hero`) are **legacy hardcoded scenes**: reuse where the
subject matches, never build new episodes around their fixed layouts, and prefer
composing from primitives + `anim` for new content. `geodesic` (a lit sphere with
drawn-on light rays) and `ripples` (concentric wave rings) are hardcoded scenes
too. (Planned: a `three` layer type
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
7. **The renderer may not lead the contract** — every draw the renderer has an
   explicit branch for must be in the contract's `DRAWS`. The safe direction
   (the contract may not name a draw the renderer cannot draw) is checked by
   `tests/test_draw_contract.py`; the reverse is checked by
   `tests/test_contract_weakening.py`, because narrowing the contract
   otherwise shrinks both sides together and stays green — measured: removing
   one entry from `DRAWS` and touching nothing else left `make verify` green.
   Two gaps that check does not cover, said out loud: a draw removed from
   BOTH the contract and the renderer stays green, and the renderer side is
   read from the source, so a branch that is present but unreachable still
   counts as implemented.

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

Mixing both is a bug, not a style choice — S3 rejects the spec with a
readable "audio conflict" error, and the S4 audio gates (silence, LUFS, AV
sync) would flag the overlap.

A clip's native track is mastered to the same -16 LUFS target as the TTS
chain, so a shot sounds the same whichever track owns it. The audio gates run
whenever the *rendered* mp4 carries a track — not only when the spec declares
an `audio` block — so a clip-owned soundtrack is measured too.

## Layer Types

1. **`ai`** — prepared image layer; `blend`, `keyColor`, `motion.zoom`, `fit`, `plate`.
2. **`video`** — prepared video layer; `asset` (an mp4), `fit`, `trim`, `loop`,
   `muted`, `motion.zoom`, `plate`. No `keyColor`: edge keying is a still-image
   concept, so a video layer skips the purity gate and is scaled to cover its
   rect instead. The clip is re-encoded at the shot's frame rate in S2 — a
   source clip at a different rate would otherwise loop over a window longer
   than itself and freeze on its last frame.
3. **`code`** — `grid | dots | bar | field | path | captions` (parameterized primitives)
   plus legacy hero scenes (see vocabulary section). `grid` and `dots` are
   prepared as an image, so they take `motion.zoom` (a camera push-in on the
   background); every other draw scales through the `anim` `scale` channel.
4. **`text`** — title/subtitle, spring or keyframe entrance, gradient or solid `color`.
5. **`hud`** — `badge | telemetry | equalizer | progress`. Decorative:
   use deliberately, not by default on every shot.
6. **`card`** — `capsule | formula | quote`.

## Quick Start

```bash
python3 pipeline.py init-shot my-shot                      # schema skeleton + design hints (no layout)
python3 pipeline.py run --spec spec/my-shot.poster.json --fixture   # free rehearsal: placeholder assets, no model call
python3 pipeline.py run --spec spec/my-shot.poster.json    # S1->S5 (visual verdict pending)
python3 pipeline.py judge --spec spec/my-shot.poster.json --verdict pass --notes "..."   # close S5
python3 pipeline.py concat --timeline spec/my-timeline.json --output build/full.mp4      # + full-video gates
python3 pipeline.py test                                   # regression suite
```

`--fixture` writes deterministic placeholder assets instead of calling a
(billed) model — rehearse the whole pipeline for free before spending. The
placeholders are registered in the ledger, so a later real run reuses them; S1
says so when it does, and `--force` makes it generate the real asset instead.
A placeholder is not a deliverable — never ship one.

### Using a generated video clip

A video layer is declared in the spec like any other layer:

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

What to expect:

- **S1 is the slow step.** It submits the clip, polls until the model
  finishes, downloads it and freezes it by sha256. `MiniMax-H3-Max` returns
  in ~20s; `MiniMax-H3` (quality) takes 15–30 minutes. The run is billed
  like any other generation call.
- **The clip is frozen after the first run.** A second `run` reuses the
  recorded asset — it does not generate a new clip. Pass `--force` to S1
  explicitly if you really want a new one.
- **`model` / `duration` / `resolution` / `ratio` are validated before the
  call.** An unknown model or a duration outside the model's range is
  rejected by `python3 pipeline.py validate`, so a typo never turns into a
  paid call that fails.
- **`muted` decides who owns the audio.** `true` (default) keeps the clip
  silent and lets the spec's `audio.voiceover` own the soundtrack; `false`
  keeps the clip's native track and `audio.voiceover` must be left empty for
  that shot. A timeline whose shots disagree on this is refused by `concat`:
  the concat demuxer would silently drop every audio track.
- **Time window.** Without `trim`, the renderer takes the clip from its
  start — a clip longer than the shot is cut at the shot's length, a shorter
  one loops (`loop: true` by default). `trim: [startSec, endSec]` selects a
  window of the clip instead; it is read in seconds at the shot's frame rate
  (S2 re-encodes every clip to that rate, so a source clip's own rate never
  applies).
- **Waiting.** S1 polls the model until it finishes: `MiniMax-H3-Max`
  ~20s, `MiniMax-H3` (quality) 15–30 minutes. Each poll prints the task
  status, so a long wait is visible rather than silent.

### Image-to-image

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

`input_asset` names a manifest asset (not a path). S1 uploads that frozen
file, hands the backend its temporary URL, and freezes the derived image the
same way it freezes a fresh one. A layer's own `prompt` replaces the style's
`subject`/`composition` — the style's `background` and `exclude` still apply
as global constraints.
