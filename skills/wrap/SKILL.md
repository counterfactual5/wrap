---
name: wrap
description: >-
  Design, synthesize, and verify code-driven short videos. The pipeline is
  zero-template: the engine ships NO visual design — no palettes, no built-in
  components, no preset scenes, no preset audio, no placeholder assets. It
  provides asset production (environment-capability-driven image/video
  generation or frozen-asset reuse), generic media compositing
  (ai/video/component layers, geometry, keyframes, springs), broadcast audio,
  and deterministic quality gates. Every video's look is authored fresh in
  the project's own components and assets.
---

# Zero-Template Video Pipeline

The pipeline treats video synthesis like compilation: a structured JSON spec
(`spec/*.poster.json`) compiles deterministically through 5 decoupled stages
(S1 Generate → S2 Prepare → S3 Compose → S4 Gate → S5 Inspect) into a gated
mp4.

**The one design law: the engine contains no design.** It ships three things:

1. **Asset production** — the authoring LLM inspects currently available tools
   (MCP tools, CLI commands) and decides the modality. If image/video tools exist,
   the LLM uses them (directly via agent tools or through S1 transport with
   capabilities declared in project `models.json`, spec, or env vars). If no
   generation tools exist in the session, the LLM authors procedural `component`
   layers (code/SVG) or reuses frozen manifest assets. No model catalog is built
   into the engine.
2. **Generic media compositing** — three layer types (`ai`, `video`,
   `component`), geometric choreography (keyframes, parenting, springs,
   camera zoom), and audio mastering.
3. **Deterministic verification** — zero-dependency pixel/audio metrics,
   quality gates, and a judge loop.

Everything visual — colors, typography, diagrams, instruments, atmosphere,
scene layouts — is authored by the project: in generated assets and in the
project's own React components. **Never import a look from another video by
default; design each video from its subject.** Re-rendering an approved spec
stays deterministic; making a *new* video means designing it fresh.

## What the engine does NOT ship (zero-template contract)

The following were removed; specs using them get an explicit
`migration required` validation error — they never render silently:

- **Code draws** `grid` / `dots` / `bar` / `field` / `path` / `captions` and
  all legacy hero scenes (`geodesic`, `trampoline`, `gravity-well`, …) —
  express them with project `component` layers.
- **Built-in `text` / `hud` / `card` layers** — typography and instruments
  are project components.
- **Palettes** — the engine resolves no colors. A component picks its own.
- **Decoration** `vibe` / `plate` / `punches` / `vibe_grade` — the render
  canvas is bare; express motion and atmosphere in components.
- **Motion presets** `gait` / `depth` material — generic `anim` keyframes,
  `spring`, and `poses` remain; locomotion is authored per project.
- **BGM presets** (`ambient`, `opera`) — `audio.bgm` takes an explicit file
  path only; a missing file is an error, the engine never synthesizes music.
- **Fixture placeholders** — the `--fixture` flag is gone; test assets live
  in `tests/`, not in the production path.
- **Built-in model catalog** — `core/generation/models.py` loads an empty
  catalog unless the environment declares one.
- **The Quartz design backend** — `renderers/quartz/` is removed; Remotion
  (Chromium) is the render engine and a renderer failure is a hard error with
  the renderer's own output, never a silent redraw by a different engine.

## Layer protocol (the entire visual vocabulary)

Three layer types. The renderer dispatches on `layer.type` and fails loudly
on anything else.

### `ai` — a still image (generated or frozen)

| field | meaning |
|---|---|
| `asset` | manifest asset name (`assets/<name>.png`, sha256-frozen) |
| `prompt` | generation prompt (S1 only; the layer's own prompt wins over any style text) |
| `input_asset` / `reference_images` | image-to-image / multi-image fusion sources (frozen assets or other `ai` assets) |
| `keyColor` + `blend` | edge keying (`#rrggbb`, `multiply`/`screen`/`normal`) |
| `cutout` (+`cutoutSimilarity`/`cutoutBlend`) | chroma cutout with `fit: "contain"` |
| `poses` | `[{frame, asset}]` — frame-switched sprite swaps (weapon arm → bare arm, …) |
| `motion.zoom` | `[z0, z1]` continuous camera push-in/pull-out on the image |
| `fit` | `cover` (crop) or `contain` (letterbox), default `cover` |

### `video` — a generated clip

| field | meaning |
|---|---|
| `asset` | frozen mp4 asset |
| `model` / `duration` / `resolution` / `first_frame` / `last_frame` / `reference_type` / `reference_images` | S1 generation parameters, validated against the **environment's declared capabilities** before any paid call |
| `trim` `[startSec, endSec]` | window into the clip (read at the shot's fps; S2 re-encodes every clip to that rate) |
| `playbackRate` | speed multiplier (audio time-stretched with pitch preserved) |
| `loop` / `muted` | loop the window; `muted: false` = the clip owns the audio |
| `fit` | `cover` (default, crops) or `contain` |
| `motion.zoom` | camera move on the clip |

### `component` — the project's own visual

| field | meaning |
|---|---|
| `component` | a name registered in the project's `remotion-custom.tsx` `CUSTOM_COMPONENTS` — an unregistered name is a hard render error |
| `rect` | the area in canvas coordinates; **the component owns its positioning** and places itself (the engine does not offset a wrapper) |
| `props` | an arbitrary opaque data bag — colors, fonts, diagram data, motion parameters; the engine interprets none of it |

Shared kinematics (any layer): `z` (strictly unique, stacking order),
`anim` (keyframes `[frame, value, ease?]` on `x/y/scale/opacity/rotate/flipX`,
eases `linear/in/out/inout/snap/overshoot/step`, applied on segment end),
`parent`/`pivot`/`joint`/`socket` (hierarchical 2D parenting; a child
inherits its ancestor chain's transforms before applying its own
`rotate`/`flipX` around `pivot`), `spring` (2nd-order inertia: `omega`,
`zeta`, `coupling`, `channel`, `driverChannel`, `maxAccel` — **all required**;
no spring defaults are provided),
`clipRect` (mask a layer to an aperture), `flipX` (mirror; for figures and
rigs, not CJK labels — mirrored glyphs are unreadable).

### `spec.tracks` — non-visual time data

Timing without presentation: when *things happen*, never how they look. You can
declare `captions`, `events`, and **arbitrary named timing tracks** (same shape:
non-empty `frame` int, ordered, non-decreasing; `captions` strictly increasing).
Components read them all.

```json
"tracks": {
  "captions": [{"frame": 90, "end_frame": 150, "text": "the clause"}],
  "events":   [{"frame": 120, "kind": "contact", "weapon": "arm-front"}],
  "chapter":  [{"frame": 300, "kind": "act2"}]
}
```

- `captions` — subtitle timing only (`frame`, optional `end_frame`, `text`).
  `sync-audio` warps these to TTS clause boundaries; **how a subtitle looks
  is a project component's job** (it reads `tracks.captions` from its props
  bag and renders what it decides).
- `events` — beats, impacts, contacts. `verify-combat` reads
  `kind: "contact"` entries; `detect-punches --apply` appends
  `kind: "audio_transient"` entries. Components read events for their own
  reactions (flash, hit-mark, zoom) — the engine triggers nothing.
- `chapter` (or another key) — a project-defined beat track; the
  engine validates shape only.

## Authoring visuals: project components

All authored visuals live in the video project, not the engine:

```tsx
// <project>/remotion-custom.tsx  — remotion.config.ts aliases `project-custom`
import type {CustomComponentRegistry} from 'remotion/registry/types';
// The alias resolves to this file when POSTER_ROOT points at the project.

export const CUSTOM_COMPONENTS: CustomComponentRegistry = {
  diagram: ({frame, fps, durationInFrames, props, prepared, preparedVideos, tracks}) => {
    // own layout, own colors, own fonts, own motion — data-driven from
    // `props` (opaque bag), `tracks` (time data), and `frame`.
    ...
  },
};
```

`CustomComponentProps` (exact contract — the engine passes nothing else):

```ts
{layer, rect, props?, prepared, preparedVideos, tracks, frame, fps, durationInFrames}
```

- `prepared` / `preparedVideos` — the top-level media layers' frozen bytes
  (data: URLs / staged clip paths), keyed by layer id: a component can draw
  over its own media without duplicating assets.
- Design every component from the video's subject. Use your Remotion authoring
  skills (markup, layout, captions, rendering) to write it fresh; the pipeline
  still owns assets, audio, determinism and the gates.
- Missing media for a declared layer, or an unregistered component name,
  fails the render with the layer named — the engine never substitutes a
  stand-in.

**Media + composition recipe.** A typical shot: `z: 0` a generated `video`
or `ai` plate (atmosphere, camera parallax) → `z: 1..n` articulated `ai`
cutouts (characters, `parent`/`joint`/`socket` rig) → `z: n+1..` one or more
`component` layers carrying the story's own diagrams, typography and
instruments, driven by `props` + `tracks`.

## Modality & Generation: The LLM Decides From Available Tools

The engine ships **no built-in model catalog** and enforces **no predetermined modality**.
Instead, **the authoring LLM inspects its current environment tools and decides:**

1. **Tool Inspection (Agent Environment)**:
   - Check available agent/MCP tools in the current session (e.g. image generation, video generation).
   - Check terminal CLIs if available (e.g. `which mcode-tools`).
   - If `mcode-tools` is installed, inspect live tool schemas via `mcode-tools connector tool <name>`.
2. **LLM Modality Decision**:
   - **Video generation tool available?** → Inspect supported models and bounds (duration, resolution, keyframe modes). Use `type: "video"` layers for fluid cinematic motion, passing the chosen `model`, `duration`, and `resolution`.
   - **Image generation tool available?** → Inspect supported aspect ratios and sizes. Use `type: "ai"` layers with explicit `prompt`, `keyColor`, etc.
   - **No generation tools available?** → The LLM sees this immediately. Choose procedural React `component` layers (100% deterministic, zero cost, crisp SVG/canvas/typography) or reuse existing frozen assets. Never fail or halt waiting for tools that don't exist.
3. **Execution & Capabilities Configuration**:
   - **Direct agent generation**: The LLM can generate assets directly via its available agent tools, save them to `assets/<asset>.png/mp4`, and register them in `manifest.json` with sha256. The pipeline verifies and composites them with zero duplicate calls.
   - **Pipeline S1 generation**: When using S1 transport, the LLM declares model capabilities via project `models.json` (`POSTER_ROOT/models.json` or `spec/models.json`), `spec.style`, or environment variables:
     - `POSTER_MODELS_JSON` (or project `models.json` `video_models`) — video model capabilities:
       ```jsonc
       {"Model-X": {
          "min_dur": 4, "max_dur": 15,        // required
          "resolutions": ["768P", "2K"],      // required
          "durations": [6, 10],              // optional discrete set
          "ratios": ["9:16"],                // optional
          "reference_types": ["first_frame"],// optional
          "audio": true, "input_image": true, "last_frame": true,
          "reference_media": false           // optional
       }}
       ```
     - `POSTER_IMAGE_CAPABILITIES_JSON` (or project `models.json` `image_models`) — image models:
       `{"Model-Y": {"aspect_ratios": ["16:9","9:16"], "areas": ["1K","2K"]}}`
     - `POSTER_VIDEO_MODEL` / `POSTER_IMAGE_MODEL` (or `default_video_model` / `default_image_model` in `models.json`) — defaults (with single candidate, auto-default).
     - `POSTER_IMAGE_AREA` — default image size tier.

Resolution ladder: explicit layer parameter > environment/project default > the
model's single declared value > **explicit error** (before any paid call).
The connector (`mcode-tools`) is a **transport adapter**, not an autonomous agent.
A shot that only reuses frozen assets, or that has no media to generate, runs the
whole pipeline with zero generation capabilities.

## Audio

**Default is silent.** Never make a video audible merely because "a soundtrack
would be nice", nor synthesize code-generated beeps on your own. An absent
`audio` block means the **shot itself** is **silent** — a compliant 44100 Hz silent
track is produced, and S4 exempts it by design. A timeline may still supply a
shared `timeline.bgm` after assembly, but that is a different, explicit choice.
Add any audio ONLY when it serves the film: (a) the user asked for a narrator /
music / SFX, (b) the shot is music-first by design choice documented in SCRIPT,
or (c) silence would hurt the beat (e.g. a video layer owns its native audio).
Never invent BGM to fill the gap; silence is a valid, first-class choice.

- **TTS owns the audio** (optional): `audio.voiceover` (text) requires an
  explicit `voice` and optional `rate`; the track is frozen to a deterministic
  local cache
  (`assets/tts_{hash}.wav`), mastered
  (highpass/EQ/compand + loudnorm to −16 LUFS). A `voice` the caller declares is
  honoured when it exists on the provider, or the call fails rather than
  silently substituting narrators. Media layers under it are
  `muted`.
- **Music-first (no voiceover)**: `audio.bgm` = an **explicit file path**
  (mastered to −16 LUFS). No presets; a missing file is an error. Only add
  when music is the vehicle of the shot.
- **The clip owns the audio**: `muted: false` on a video layer, and
  `audio.voiceover` left empty for that shot. **At most one** video layer may be
  unmuted — two unmuted tracks own the soundtrack and the encoder refuses.
- **Pure silent shot (default)**: no `audio` block — a compliant 44100 Hz
  silent track is produced; S4 exempts it by design.
- Mixing TTS/BGM and an unmuted clip in one shot is refused at validate/S3
  ("audio conflict"). `sync-audio` aligns `durationInFrames` and `tracks.captions` to
  the synthesized TTS clause timings and piecewise-warps every layer's
  keyframes/poses/events, so visuals stay locked to speech.
- **TTS fallback is explicit, never fake**: if Synthesis fails on Edge TTS,
  Google TTS and macOS `say`, S1 raises an error and the voiceover does not ship
  as an unintelligible cadence. The only offline voices are the ones the local
  provider can actually produce.

**Freeze/black opt-outs.** A shot spec can declare `frame_freeze: true` to permit
frozen frames (S4 skips freezedetect); a timeline can declare `allow_black: true`
to permit intentional black frames (full-video gate skips blackdetect). Use
them only when the still/black is the intended design, not to dodge a failure.

## The 5 stages + judge loop

| Stage | Script | Contract | Exit |
|---|---|---|---|
| S1 Generate | `stages/01_generate.py` | Generate/verify assets into `assets/`, freeze sha256 in `manifest.json`; generation parameters checked against declared capabilities **before** the call; frozen-asset reuse never requires a model | 0 / 1 |
| S2 Prepare | `stages/02_prepare.py` | Key purity (≥ 0.98), aspect-true scaling, clip re-encode to shot fps → `build/prepared/{shot}/` | 0 / 1 |
| S3 Compose | `stages/03_compose.py` | Remotion render → `build/frames/{shot}/%05d.png` + `build/{shot}.mp4` (BT.709, mastered audio); a renderer failure is a hard error reporting the renderer's own output | 0 / 1 |
| S4 Gate | `stages/04_gate.py` | Motion/accent/purity/freeze + audio QC (silence > −45 dB, LUFS in [−19, −13], AV sync ≤ 100 ms) → `build/gates/{shot}.json`. Color gates must declare their `color` explicitly — the engine guesses nothing | 0 / 1 |
| S5 Inspect | `stages/05_inspect.py` | Contact sheet + **project-declared** `spec.checklist` items + asset/track inventory. Verdict is `pending_judge` (`pass: null`) | 0 |
| S5+ Judge | `pipeline.py judge --verdict pass\|fail --notes` | A model or human reads the sheet against the checklist; `fail` exits 1 (hard gate). An S4 re-run invalidates a stale verdict | 0 / 1 |

`pipeline.py concat` / `run --timeline` add whole-film gates: timeline
duration delta ≤ 250 ms, zero digital-black intervals, whole-track
silence/loudness, AV alignment ≤ 250 ms, per-segment loudness jump ≤ 3 LU
→ `build/gates_full_{timeline_id}.json`.

### Multi-shot timelines (Image → Clip → Seam → Film)

The manifest is **project-scoped**: shot k+1 may reference an asset shot k
generated. The order matters — shot k must have GENERATED before shot k+1's
S1 runs.

- **Frame seam (truthful)**: `pipeline.py extract-frame --video build/shot-01.mp4
  --name shot-01-tail --at last` freezes shot k's rendered tail as an asset;
  shot k+1 names it as `first_frame` — it starts on the exact pixels shot k
  ended on. `run --timeline` freezes `<name>-tail` seams as it goes.
- **Asset seam (cheap)**: both shots name the same asset — the model's
  approximation, not exact pixels.
- `run --timeline` renders shots in order, freezes seams, assembles, and
  gates the film. It does not invent seams, re-order shots, or close the
  visual audit — the judge verdict stays per-shot, yours to give. `--force`
  re-generates assets instead of reusing frozen ones.

## Quick start

```bash
# python >= 3.10 required (engine uses int.bit_count); `make` probes
# python3.13/3.12/3.11/3.10 automatically.
python3 pipeline.py init-shot my-shot --canvas 1080 1920 --fps 30 --frames 450
python3 pipeline.py run --spec spec/my-shot.poster.json          # S1 -> S5
python3 pipeline.py run --timeline spec/timeline.json --output build/film.mp4
python3 pipeline.py judge --spec spec/my-shot.poster.json --verdict pass --notes "..."
python3 pipeline.py sync-audio --spec spec/my-shot.poster.json   # clause-anchored TTS sync
python3 pipeline.py verify-rig --spec spec/my-shot.poster.json
python3 pipeline.py test                                         # regression suite
```

`init-shot` demands **explicit** `--canvas W H`, `--fps N`, `--frames N`:
it writes a schema skeleton with zero layers, zero design and no defaults
borrowed from any template. The skeleton says nothing about what the shot
should look like — that is your design decision.

## 2D skeletal rigging (geometry only)

For multi-part image rigs (characters, puppets, props) the engine provides
generic geometry — no acting presets and no material model:

- **Parenting & sockets** — a child layer: `parent`, `joint` (in child asset
  pixels), `pivot` (in canvas coordinates); the parent declares `sockets`.
  `pipeline.py snap-joint` computes the exact `rect`/`pivot`;
  `verify-rig` checks sub-pixel alignment (delta ≤ 2 px).
- **`poses`** — frame-switched sprite swaps on an `ai` layer.
- **`spring`** — secondary motion (inertia lag/overshoot) driven by a
  channel of the parent.
- **`verify-blocking`** — co-planar characters must not overlap in the same
  horizontal lane (lane separation + max overlap).
- **`verify-combat`** — weapon-tip/target contact on the `tracks.events`
  `kind: "contact"` frames.
- **`verify-continuity`** — geometric scene handoffs: background
  continuity, character position continuity (delta ≤ 15 px) between shots.

Acting decisions (which pose, when, with what spring values) are authored in
the spec per video; the engine verifies geometry, not performance.

## Authoring pitfalls (measured on real renders)

1. **`z` is unique per shot** — `validate` rejects duplicates; stacking is
   undefined without it.
2. **A still shot fails the motion and freeze gates** — pair static media
   with `motion.zoom`, `anim` keyframes, or active component animation.
3. **Shot k generates before shot k+1's S1** — later shots may name assets
   the earlier shot froze.
4. **A generation reference must be a frozen image asset** — `first_frame` /
   `reference_images` resolve through the manifest; live-drawn content has
   no file to hand to the model. Render a component's output to a frame and
   freeze it (`extract-frame`) if you need it as a reference.
5. **Short voiceover lines sit near the loudness gate edge** — 4 characters
   in a 5 s shot lands near −13 LUFS against the −16 target; 15+ characters
   lands solidly in [−16, −15].
6. **One timeline, one audio ownership per shot** — every rendered mp4
   carries an audio stream (silent shots get a compliant silent one), but
   mixed ownership across shots is refused at `concat`.
7. **A `video` layer defaults to `cover` and CROPS** — a 9:16 clip in a
   16:9 rect shows ~32% of its height; motion outside the window can make
   the shot read frozen. Match clip aspect to rect, or `fit: "contain"`, or
   keep the motion inside the visible window.
8. **Browser-rendered shots are content-reproducible, not byte-reproducible** —
   Chromium's font antialiasing rounds a few pixels between runs; media-only
   shots with no text-bearing component are the byte-exact ones.
9. **An unregistered component name is a hard error** — there is no
   stand-in box; register it in `remotion-custom.tsx` or rename the layer.
10. **No model capability → generation fails at the call site, before money
   moves** — declare `POSTER_MODELS_JSON`/`POSTER_IMAGE_CAPABILITIES_JSON`
   for the environment; reuse frozen assets to work around a missing
   backend, never placeholders.
