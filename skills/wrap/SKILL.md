---
name: wrap
description: >-
  Design, synthesize, and verify code-driven short videos with this repo's
  zero-template engine: a JSON spec compiles through S0 + S1–S5 into a
  gated mp4. The engine ships NO visual design — asset production,
  ai/video/component compositing (geometry, keyframes, springs), audio and
  deterministic quality gates only; every video's look is authored fresh in
  the project's own components and assets. Use when the user asks to create,
  render, gate, review or deliver a video with this pipeline (spec files,
  pipeline.py, Remotion), mentions this skill, or asks how the engine works.
---

# Zero-Template Video Pipeline

The pipeline treats video synthesis like compilation: a structured JSON spec
(`spec/*.poster.json`) compiles deterministically through S0 (author the
script — Screenwriter, plus Researcher when `kind` is scientific/educational,
plus a reviewer with no author lobbying) + 5 decoupled stages
(S1 Generate → S2 Prepare → S3 Compose → S4 Gate → S5 Inspect) into a gated
mp4. When the environment supports subagents, run the stages as a
multi-agent pipeline of roles — see **Authoring orchestration** below and
`references/orchestration.md`.

**The one design law: the engine contains no design.** It ships three things:

1. **Asset production** — the authoring LLM inspects currently available tools
   (MCP tools, CLI commands) and decides the modality. When image/video tools
   suit the story and usage is permitted, the LLM may use them (directly via agent tools or through S1 transport with
   capabilities declared in project `models.json` or env vars — `spec.style` only names default selections, never capabilities). If no
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
| `prompt` | generation prompt (S1 only). The layer's own prompt is the **only** prompt source — `style` files contribute nothing to prompts; poses may carry their own |
| `input_asset` / `reference_images` | image-to-image / multi-image fusion sources (frozen assets or other `ai` assets) |
| `keyColor` + `blend` | edge keying (`#rrggbb`, `multiply`/`screen`/`normal`) |
| `cutout` (+`cutoutSimilarity`/`cutoutBlend`, both required when `cutout:true`) | chroma cutout with `fit: "contain"` |
| `poses` | `[{frame, asset}]` — frame-switched sprite swaps (weapon arm → bare arm, …) |
| `motion.zoom` | `[z0, z1]` continuous camera push-in/pull-out on the image |
| `fit` | `cover` (crop) or `contain` (letterbox), default `cover` |
| `backdrop` | project-declared identity of this layer's background (a string; the same string across two shots means "the same place") — read by `verify-continuity` for the cross-shot backdrop handoff, never inferred |

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

Compose media and project components only as the story requires; there is no
prescribed layering recipe. The `props` and `tracks` passed to components carry
project-authored data, not a built-in design.

Two files in this skill make this step less hollow — read both **before**
writing your first component:

- [`references/design-craft.md`](references/design-craft.md) — visual authoring
  heuristics (type in motion, one-accent color, change-on-the-beat, canvas
  safe areas, rhythm/ASL, failure smells). Principles and questions, not
  prescriptions; flat and monochrome are valid answers.
- [`references/example.md`](references/example.md) — one minimal shot run
  end-to-end on this repo (spec + component + gates + judge notes). Copy the
  *shape* — props bag, frame math, median-proof motion — never the look.

## Modality & Generation: The LLM Decides From Available Tools

The engine ships **no built-in model catalog** and enforces **no predetermined modality**.
Instead, **the authoring LLM inspects its current environment tools and decides:**

1. **Tool Inspection (Agent Environment)**:
   - Check available agent/MCP tools in the current session (e.g. image generation, video generation).
   - Check terminal CLIs if available (e.g. `which mcode-tools`).
   - If `mcode-tools` is installed, inspect live tool schemas via `mcode-tools connector tool <name>`.
2. **LLM Modality Decision**:
   - Compare video, images, procedural components, simulation and combinations against the subject, visual intent, consistency, editability, actual capabilities and authorized cost. Availability does not mandate use or impose a video-first priority.
   - **Where the value lives** — name what the shot is actually for, then let that name the candidate approaches; it is a prompt for your own options, not a lookup table:
     | The shot's value is… | Candidate approaches worth considering |
     |---|---|
     | Precision (diagrams, formulas, data, geometry) | procedural `component` layers; typed charts |
     | Craft (drawn/painted texture; objects that must *act*) | generated stills + rig (`poses`/parenting/springs); hand-drawn components; generated video |
     | Motion / photorealism as the subject | generated video (independent shots, or a seam-chained i2v backbone); physical simulation; rigged assets |

     Every row stays open: characters can be generated video instead of
     rigged stills, water and fire can be simulated instead of generated,
     a realistic film can be independent shots rather than a chain.
     **The table proposes, it does not assign** — propose candidates, then
     verify with a short rendered proof against capability, budget and the
     brief. Mixing is normal (rigged or component information over a
     generated world). The failure worth naming is the *silent* one: a
     subject whose value is motion, built as a still plus a slow push,
     passes every gate and still reads dead (see `references/pitfalls.md` §14).
   - For video inspect supported duration/resolution/keyframe modes before selecting `type: "video"`; for images inspect sizes/aspect ratios before selecting `type: "ai"`. Record why the chosen approach serves the film.
   - **No generation tools available?** → The LLM sees this immediately. Choose procedural React `component` layers (no generation-service charge; local rendering still consumes resources) or reuse existing frozen assets. Never fail or halt waiting for tools that don't exist.
3. **Execution & Capabilities Configuration**:
   - **Direct agent generation**: Check actual tool parameters, permissions and budget before invoking the tool; S1 cannot preflight calls made outside S1. The LLM can generate assets directly via its available agent tools, save them to `assets/<asset>.png/mp4`, and register them in `manifest.json` with sha256. The pipeline verifies and composites them with zero duplicate calls.
   - **Pipeline S1 generation**: When using S1 transport, the LLM declares model capabilities via project `models.json` (`POSTER_ROOT/models.json` or `spec/models.json`) or environment variables. `spec.style` never declares capabilities — it is a JSON file path that only names default *selections* (`videoModel` / `videoResolution` / `imageModel` / `area`):
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
track is produced; S4 checks silence and AV alignment, not audible-track loudness. A timeline may still supply a
shared `timeline.bgm` after assembly, but overriding an intentionally silent
shot also requires `allow_bgm_override_silent: true` in the timeline.
Add voice, music, sound effects or native clip audio only when authorized by
the user. A design choice documented in SCRIPT is not authorization. Silence
is a valid, first-class choice; generated video defaults to muted.
- **TTS owns the audio** (optional): `audio.voiceover` (text) requires an
  explicit `voice` and optional `rate`; the track is frozen to a deterministic
  local cache
  (`assets/tts_{hash}.wav`), mastered
  (highpass/EQ/compand + loudnorm to −16 LUFS). A `voice` the caller declares is
  honoured when it exists on the provider, or the call fails rather than
  silently substituting narrators. Media layers under it are
  `muted`. `audio.voiceover` may also name an already-registered audio **file**
  (`.wav/.mp3/.aac/.m4a/.ogg/.flac`) instead of text — the bytes are verified
  and copied through, no `voice` needed; a file-like value that does not
  resolve is a hard error.
- **Music-first (no voiceover)**: `audio.bgm` = an **explicit file path**
  (mastered to −16 LUFS). No presets; a missing file is an error. Only add
  when music is the vehicle of the shot.
- **The clip owns the audio**: `muted: false` on a video layer, and
  `audio.voiceover` left empty for that shot. **At most one** video layer may be
  unmuted — two unmuted tracks own the soundtrack and the encoder refuses.
- **Voice + BGM**: both set → spec.audio `bgmUnderVoice` (0..1, e.g. 0.25)
  is REQUIRED — the engine ships no default duck ratio; voice-only or
  music-only shots run full volume. A timeline bed mixed under audible shot
  audio needs the same declaration on the timeline (`timeline.bgmUnderVoice`);
  beds over fully-silent films are mastered to −16 LUFS alone.
- Mixing TTS/BGM and an unmuted clip in one shot is refused at validate/S3
  ("audio conflict"). `sync-audio` aligns `durationInFrames` and `tracks.captions` to
  the synthesized TTS clause timings and piecewise-warps every layer's
  keyframes/poses/events, so visuals stay locked to speech.
- **TTS fallback is explicit, never fake**: if synthesis fails on Edge TTS and
  macOS `say`, S1 raises an error and the voiceover does not ship
  as an unintelligible cadence. The only offline voices are the ones the local
  provider can actually produce. A voice neither provider can produce is a
  hard error — the engine never silently swaps in a different narrator.

**Freeze/black opt-outs.** A shot spec can declare `frame_freeze: true` to permit
frozen frames (S4 skips freezedetect); a timeline can declare `allow_black: true`
to permit intentional black frames (full-video gate skips blackdetect). Use
them only when the still/black is the intended design, not to dodge a failure.

### Audio asset integrity

Before using an existing BGM or voiceover file, independently verify its source
and content, then register its current bytes in the project manifest:

```bash
POSTER_ROOT=/path/to/project python3 -m core.audio.integrity register /path/to/audio.wav
```

Run this from the engine root, or make the engine importable via `PYTHONPATH`.
Unregistered or changed audio fails verification rather than being silently
trusted again. This is a migration requirement for existing projects. Generated
TTS cache audio and its timing metadata are also registered and verified; old
unregistered cache files must be reviewed and registered separately or removed
with their ledger entries before regeneration. External absolute paths remain
bound to their location. These checks detect changed bytes, not licensing or
content quality.

## S0 · Intent and script before production

S0 is an authoring protocol, not a `pipeline.py` command. Before generating
assets or implementing scenes, write `<project>/SCRIPT.md`:

- Audience, purpose, intended feeling, and the one takeaway or experience.
- A sequence of beats with their narrative jobs, final copy (if any), image
  actions, transitions and estimated reading/viewing time. Choose the number
  of beats from the subject and duration; there is no six-beat requirement.
- A consistent voice and meaningful progression. Resolve promises made by the
  opening; a recurring motif is optional, not a compulsory storytelling device.
- For factual work, link consequential claims to actual sources and record
  uncertainty. Model memory or a reviewer agreeing is not source verification.
- State duration, format, resource budget and audio policy. Estimate total
  reading load, including simultaneous text and transition time. Staggering
  lines does not remove their combined reading cost.
- **`kind` — declare what kind of claim this film makes** (project-level,
  not engine-level): `scientific` / `educational` / `narrative` / `mood`.
  This single declaration determines which steps are mandatory and which are
  skippable:

  | kind | Must contain | Not required |
  |---|---|---|
  | `scientific` | verifiable claims; `reports/research.md`; fact-review pass; `fact-boundary` section in SCRIPT | — |
  | `educational` | steps must be followable; `reports/research.md` or explicit `model-knowledge-unverified` flags; fact-review pass | `fact-boundary` |
  | `narrative` | chain of causality intact; no scientific auditing of the world (but fictions still must not masquerade as fact); fact review only if a claim is load-bearing | `research.md`; `fact-boundary` |
  | `mood` | no fact-review required; no `consequential claims` to check; `fact-boundary` section in SCRIPT | `research.md`; fact review; scientific verification |

  The S5 checklist and the reviewer's brief are both generated from `kind`;
  nothing about the engine or the gates changes.

Titles may be fragments, labels or complete sentences if intentional and
unambiguous. Neither subject–verb grammar nor a title/subtitle/footer layout
is mandatory. Silent films need not fill the screen with text.

Review the script before production (independent reviewer in T1/T2; explicitly
labelled self-review in T3). Resolve material narrative and factual issues.
Include project-specific narrative and audience-comprehension checks in
`spec.checklist`; checklist wording is an agent requirement, not a schema gate.

## The engine pipeline (S0 + 5 stages + judge loop)

| Stage | Script | Contract | Exit |
|---|---|---|---|
| S1 Generate | `stages/01_generate.py` | Generate/verify assets into `assets/`, freeze sha256 in `manifest.json`; generation parameters checked against declared capabilities **before** the call; frozen-asset reuse never requires a model | 0 / 1 |
| S2 Prepare | `stages/02_prepare.py` | Key purity (≥ 0.98), aspect-true scaling, clip re-encode to shot fps → `build/prepared/{shot}/` (`2` = hard error: unverified asset / still-as-clip, not a failed gate) | 0 / 1 / 2 |
| S3 Compose | `stages/03_compose.py` | Remotion render → `build/frames/{shot}/%05d.png` + `build/{shot}.mp4` (BT.709, mastered audio); a renderer failure is a hard error reporting the renderer's own output | 0 / 1 |
| S4 Gate | `stages/04_gate.py` | Motion/accent/purity/freeze + audio QC (silent peak < −45 dB, audible-track loudness (LUFS in [−19, −13], silent shots skip), AV sync ≤ 100 ms) → `build/gates/{shot}.json`. Color gates must declare their `color` explicitly — the engine guesses nothing | 0 / 1 |
| S5 Inspect | `stages/05_inspect.py` | Contact sheet + **project-declared** `spec.checklist` items + asset/track inventory. Verdict is `pending_judge` (`pass: null`). The checklist **must carry ≥ 1 visual plausibility item** (e.g. "the figure/object reads as what it claims to be"), **≥ 1 narrative-coherence item** (see S0), and for checklist reviewers: they must name at least one **specific defect** in the render or explicitly justify "no defects found" with evidence — a purely mechanical checklist is defective | 0 |
| S5 Judge | `pipeline.py judge --verdict pass\|fail --notes` | A model or human reads the sheet against the checklist; `fail` exits 1 (hard gate). An S4 re-run invalidates a stale verdict. In T1/T2 use a **fresh** reviewer with no author lobbying; T3 is explicitly self-review | 0 / 1 |

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

#### The seam-chained i2v path

A named production mode with its own budget shape — see
[`references/seam-chained-i2v.md`](references/seam-chained-i2v.md). Decide
chained vs independent shots at Brief time; each chained shot k+1 needs
shot k's rendered tail as `first_frame`, and the regeneration reserve is
not optional.

## Authoring orchestration (distinct from engine S1–S5)

The engine compiles media; the agent protocol develops a film. The full
playbook lives in [`references/orchestration.md`](references/orchestration.md):
tier selection (T1 peer / T2 subagent pipeline / T3 serial), the dispatch
rule (WHO always dispatches; HOW only when the evidence changes the
decision), the production sequence and its fast path, the zero-template
quality contract, bounded communication, and budgets / provenance /
truthful reporting.

Read it **before** a multi-agent production run. It is **not** needed for
a single-shot or a SMALL-WORK fast-path edit (one read of the stage table
plus the final review labelled honestly suffice), and in T3 every review
is self-review — label it as such.

One lesson worth carrying out of the playbook even in T3: the
**subject-literalism guard** — name the subject's single most iconic image
and make sure the film actually shows it. A chain of specialists each
executing the upstream document faithfully can still produce a film that
never shows the one thing the subject is *known for*; see
`references/orchestration.md` § Subject-literalism guard.

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
make verify                                                # offline regression suite (== python3 pipeline.py test)
```

`init-shot` demands **explicit** `--canvas W H`, `--fps N`, `--frames N`:
it writes a schema skeleton with zero layers, zero design and no defaults
borrowed from any template. The skeleton says nothing about what the shot
should look like — that is your design decision. A minimal shot built and
gated end to end (spec + component + judge) is in
[`references/example.md`](references/example.md) — the fastest way to see a
complete pass on this engine.

This manual is the contract and the map, not an exhaustive flag reference:
`python3 pipeline.py -h` is the source of truth for subcommands it does not
list (`validate`, `inspect-sprite`, `derive-poses`, `unpack-kit`, …).

## 2D skeletal rigging (geometry only)

For multi-part image rigs (characters, puppets, props) the engine provides
generic geometry — no acting presets and no material model:

- **`verify-rig`** — skeletal puppet joint alignment, socket calibration,
  rendered diagnostic overlay. Asset-backed layers verify against the frozen
  manifest; project component layers verify against their declared `rect`.
  Both paths use the same `snap_socket_joint` math (scale=1.0 for components).
- **`poses`** — frame-switched sprite swaps on an `ai` layer.
- **`spring`** — secondary motion (inertia lag/overshoot) driven by a
  channel of the parent.
- **`verify-blocking`** — co-planar characters must not overlap in the same
  horizontal lane (`--max-overlap`, `--min-visible-opacity`). Discovers
  `ai` + `cutout` characters and `component` + `role` humanoid/quadruped/mech
  characters. The torso band is measured: for asset layers it is derived from
  the opaque-pixel bounding box; for asset-less and component characters it
  is declared as `blockCore` [leftFrac, rightFrac] in [0,1] on the layer —
  missing is a failed verdict, not a fallback. Exemptions are declared
  (`role: "prop"` or invisible characters); no guessed exemptions.
- **`verify-combat`** — weapon-tip/target contact on the `tracks.events`
  `kind: "contact"` frames. Weapon geometry is declared, never guessed:
  `spec.combat` carries `attacker`/`weapon`/`target`, `tipOffset` (tip vs
  pivot, source px) and `refWidth`; missing values are a failed verdict,
  not a guess.
- **`verify-continuity`** — cross-shot handoffs: shot k's tail backdrop must
  equal shot k+1's opening backdrop (mismatch = hard failure unless
  `--allow-non-seamless` or the timeline's `continuity` block sets
  `require_seamless_handoff: false`, which downgrades it to BACKDROP_WARN),
  and a character visible (opacity ≥ `--min-visible-opacity`, default 0.20)
  on both sides of a cut must not jump more than `--max-jump` (default 18 px).
  Defaults come from the timeline's optional `continuity` block
  (`max_char_jump_px` / `require_seamless_handoff` / `min_visible_opacity`,
  validated at load); CLI flags override. `--spec` mode runs the generic
  stagecraft report (spec validation + backdrop/character states) and takes
  no continuity knobs.
  **A cut whose layers declare no `backdrop` identity is reported as
  NOT CHECKED, never as PASS** — the backdrop identity is a project
  declaration (`layer.backdrop`, a string that means "same place" across two
  shots); without it there is nothing to compare and the engine says so.

Acting decisions (which pose, when, with what spring values) are authored in
the spec per video; the engine verifies geometry, not performance.

## Authoring pitfalls

Sixteen measured pitfalls live in [`references/pitfalls.md`](references/pitfalls.md).
The three that sink the most first-time runs:

1. **Gates measure "not broken", never "alive"** — prove motion with a short
   rendered proof, or own stillness explicitly (`frame_freeze` + intent).
2. **A generation reference must be a frozen asset** in the manifest —
   render a component to a frame and `extract-frame` it if needed.
3. **`z` is unique per shot, and browser-rendered frames are only
   content-reproducible** (Chromium antialiasing rounds a few pixels).

