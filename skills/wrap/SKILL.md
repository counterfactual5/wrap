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
(`spec/*.poster.json`) compiles deterministically through S0 (author the
script, ideally as Researcher + Screenwriter + Skeptics) + 5 decoupled stages
(S1 Generate → S2 Prepare → S3 Compose → S4 Gate → S5 Inspect) into a gated
mp4. When the environment supports subagents, run the stages as a
multi-agent pipeline of roles — see **Orchestrated mode** below.

**The one design law: the engine contains no design.** It ships three things:

1. **Asset production** — the authoring LLM inspects currently available tools
   (MCP tools, CLI commands) and decides the modality. When image/video tools
   suit the story and usage is permitted, the LLM may use them (directly via agent tools or through S1 transport with
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

Compose media and project components only as the story requires; there is no
prescribed layering recipe. The `props` and `tracks` passed to components carry
project-authored data, not a built-in design.

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

     Every row stays open: characters can be generated video instead of rigged stills, water and fire can be simulated instead of generated, a realistic film can be independent shots rather than a chain. **The table proposes, it does not assign** — propose candidates, then verify with a short rendered proof against capability, budget and the brief. Mixing is normal (rigged or component information over a generated world). The failure worth naming is the *silent* one: a subject whose value is motion, built as a still plus a slow push, passes every gate and still reads dead (see pitfall 14).
   - For video inspect supported duration/resolution/keyframe modes before selecting `type: "video"`; for images inspect sizes/aspect ratios before selecting `type: "ai"`. Record why the chosen approach serves the film.
   - **No generation tools available?** → The LLM sees this immediately. Choose procedural React `component` layers (no generation-service charge; local rendering still consumes resources) or reuse existing frozen assets. Never fail or halt waiting for tools that don't exist.
3. **Execution & Capabilities Configuration**:
   - **Direct agent generation**: Check actual tool parameters, permissions and budget before invoking the tool; S1 cannot preflight calls made outside S1. The LLM can generate assets directly via its available agent tools, save them to `assets/<asset>.png/mp4`, and register them in `manifest.json` with sha256. The pipeline verifies and composites them with zero duplicate calls.
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
  `muted`.
- **Music-first (no voiceover)**: `audio.bgm` = an **explicit file path**
  (mastered to −16 LUFS). No presets; a missing file is an error. Only add
  when music is the vehicle of the shot.
- **The clip owns the audio**: `muted: false` on a video layer, and
  `audio.voiceover` left empty for that shot. **At most one** video layer may be
  unmuted — two unmuted tracks own the soundtrack and the encoder refuses.
- **Pure silent shot (default)**: no `audio` block — a compliant 44100 Hz
  silent track is produced; S4 checks silence and AV alignment.
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

## S0 + 5 stages + judge loop

| Stage | Script | Contract | Exit |
|---|---|---|---|
| S1 Generate | `stages/01_generate.py` | Generate/verify assets into `assets/`, freeze sha256 in `manifest.json`; generation parameters checked against declared capabilities **before** the call; frozen-asset reuse never requires a model | 0 / 1 |
| S2 Prepare | `stages/02_prepare.py` | Key purity (≥ 0.98), aspect-true scaling, clip re-encode to shot fps → `build/prepared/{shot}/` | 0 / 1 |
| S3 Compose | `stages/03_compose.py` | Remotion render → `build/frames/{shot}/%05d.png` + `build/{shot}.mp4` (BT.709, mastered audio); a renderer failure is a hard error reporting the renderer's own output | 0 / 1 |
| S4 Gate | `stages/04_gate.py` | Motion/accent/purity/freeze + audio QC (silent peak < −45 dB,audible-track loudness (LUFS in [−19, −13], silent shots skip), AV sync ≤ 100 ms) → `build/gates/{shot}.json`. Color gates must declare their `color` explicitly — the engine guesses nothing | 0 / 1 |
| S5 Inspect | `stages/05_inspect.py` | Contact sheet + **project-declared** `spec.checklist` items + asset/track inventory. Verdict is `pending_judge` (`pass: null`). The checklist **must carry ≥ 1 narrative-coherence item** (see S0); a purely visual checklist is a defective one | 0 |
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

#### The seam-chained i2v path (one production mode among several)

When a film is built from generated video chained by frame seams — the
"where the value is motion" row may lead here, but so may other routes —
treat it as a named mode with its own budget shape, decided at Brief time
rather than improvised per shot:

- **Budget arithmetic** (state it in `CONCEPT.md` before any paid call):
  an N-shot seam-chained backbone = **N generations + N−1 seam freezes + a
  regeneration reserve per failed shot**. When shots are chained by their
  predecessor's last frame, production is strictly left-to-right: shot k+1's
  first_frame does not exist until shot k is rendered, so a failed shot
  mid-chain blocks everything after it — the reserve is not optional.
  Independent shots (no seam dependency) can be produced in any order and
  do not inherit that serialisation; say which shots are chained and which
  are not.
- Include in the budget: the reference stills (frozen `ai` assets or
  `extract-frame` output), the billable duration/resolution of every
  generation, generations that were paid for but rejected, and a hard spend
  ceiling. "N generations" counts calls, not money.
- Author each chained shot from a still YOU control (frozen `ai` asset or
  `extract-frame` output), never from a live unsaved render — a generation
  reference must resolve through the manifest.
- A seam is a continuity *device*, not a guarantee: character identity,
  materials and motion speed can drift across a long chain, so inspect the
  assembled seams, not only the individual shots.
- Known engine boundaries for this mode: clips re-encode to the shot's fps
  and pixel format in S2 (no alpha survives — see pitfall 15); loop seams of
  a single clip inside one shot are the model's cycle, visible if the motion
  is fast; plan shot lengths against the model's `max_dur`, not against hope.

## Authoring orchestration (distinct from engine S1–S5)

The engine compiles media; the agent protocol develops a film. The production
steps below are NOT additional CLI stages. Technical success does not imply
editorial or aesthetic success. Do not label a self-review independent.

### Runtime topology: probe capabilities, not host names

No host-specific documents are required. At the start of a production run,
inspect the current tool schemas and actual responses. Keep a run record in
`reports/runtime-probe.md`, not a permanent host capability catalogue.

| Tier | Selection rule | Execution |
|---|---|---|
| T1 · peer | Delegation works AND peers have a verified direct messaging path, with safe completion/wakeup and write-ownership handling | Director coordinates; authorized peers exchange bounded evidence directly |
| T2 · subagent pipeline | Delegation works; peer delivery absent, or present without verified completion/wakeup/write-ownership handling | Director dispatches roles and relays findings verbatim; preserve evidence and dissent; never claim peer delivery |
| T3 · serial | Delegation absent, unavailable, or user requests single-agent execution | Main agent executes roles sequentially; review is self-review, not independent approval |

Decision procedure (also applies without any environment documentation):

1. Inspect delegation, peer messaging, resume/wakeup, completion, cancellation,
   workspace sharing and image-viewing capabilities. Unknown is not supported.
   A parent-to-child follow-up tool alone does not prove peer messaging.
2. No delegation: T3. Delegation with no verified peer path: T2. Use the first
   real, small task to verify dispatch; no mandatory synthetic dispatch for T2.
   Missing resume does not force T3: re-dispatch with a self-contained handoff.
3. Only test T1 if schemas plausibly permit peer delivery. Use one bounded
   handshake, at most two probe instances and one send/reply round. The sender
   creates a nonce after dispatch and sends it via the peer channel; the
   receiver reports the nonce, sender and transport without a Director relay.
   Obtain real receipts from both sides when the host provides them; otherwise require a default-ON written acknowledgement from both instances and downgrade to T2 without it. Never block indefinitely;
   if the host cannot safely complete this test, stay T2. Count all probe
   instances/calls honestly; this is not a one-dispatch test.
4. Record observed/unknown capabilities, chosen tier and evidence. Cache for
   this run; recheck on tool changes or failures, not before every task.

**Switching hosts for T1 buys fidelity first; the speed effect is unmeasured.**
T1 removes the Director's relay step, so it can cut main-thread turns, and
resumable instances may allow more overlap — but the size of that gain is not
known: the earlier split (serial chain / dispatch latency / relay / render)
was an estimate, not a timed measurement. Do not quote percentages for T1
savings without recording dispatch, wait, relay and render times first. For
throughput, start with the levers that do not depend on the host: scale the
roster (see Production sequence), run research and script speculatively,
resume instances instead of re-dispatching, and batch relay rounds.

Failure downgrades apply to the affected exchange/task, not automatically to
all roles. Direct delivery failure → T2; unavailable delegation → T3. Record
which review lost independence. A timeout does NOT prove a writer stopped:
confirm termination before assigning the same write domain to another agent
or editing it in the main thread; otherwise stop that write domain and report.
Do not blindly repeat a known-failing operation. Respect tool/model budgets.

### Production sequence and dispatch

Director orchestrates; subagents produce. The main thread does not author the
film itself — that is the difference between this pipeline and "just asking the
model to make a video", and also where the cost sits.

Default rule: **every task that can be executed is dispatched**. Director keeps
only this exclusively: scope, budgets, final design selection, integration,
gate execution, final visual verdict, delivery. Everything else is outsourced.

The one question per candidate dispatch:

> Does this spawn change **who does the work**, or **how we know it's good**?

- **WHO** — always dispatch; the dispatch itself is the work. Screenwriter
  writes the script; Art Director(s) visualise; Builders implement per disjoint
  files; Researcher gathers facts. Director does not sub-contract its judgement,
  but judgement ≠ writing.
- **HOW we know** — dispatch is conditional. A second checker is spent only
  when the evidence it produces changes the decision: a fresh eye that could
  catch what the author can't, or a parallel arm that produces options the
  main thread would not.

Apply the rule to each segment; do not pre-fill a roster, do not dispatch for
show:

| Segment | Default | Escalate when |
|---|---|---|
| S0 script | Dispatch 1 Screenwriter (+ 1 fact reviewer **only if** the `kind` requires it) | Reviewer finds causal error → 1 resize/rewrite |
| S1 design | Dispatch 1 Art Director per candidate direction **only** if the design space is open; otherwise 1 | Ambiguous brief or two genuinely viable styles → +1 arm for comparison |
| S1 shotlist / plan | Director writes; skip if the brief is a single shot (state skip in one line) | — |
| S2 build | Dispatch builders per disjoint file domain; parallel when profitable | Any file-domain task that is non-trivial and has no owner |
| S3 render | Director runs render | — |
| S4 gates | Director runs gates; no subagent; fix loop only if failure — then dispatch the fix | Gate tells you *which file*; dispatch only that owner |
| S4.5 rendered review | 0 or 1 fresh Visual Reviewer, only if the render is novel / error-prone / adjudication-blocking | Authoring blind spot likely: unusual camera, POV, typography, or a prior near-miss on the same brief |
| S5 final review | 1 fresh reviewer (T1/T2); T3 = self-review, labelled | verdict == fail → rewire; needs-work → owner re-renders |
| S6 delivery | Director alone | — |

**SMALL-WORK FAST PATH.** One-line copy, one color/position/timing tweak, a
single-layer edit — Director handles these alone (run the gate, look at the
affected frame, ship), *because spawning a subagent costs more than the edit*.
This is the only place the default reverses. The line between "small" and
"not": does this edit change what the viewer takes away? If yes, it's work —
dispatch it.

**DECISION LOG.** Every skipped dispatch writes one line in `reports/` saying
why it was skipped. No silent omissions. Growing and shrinking the roster both
need a reason; free-riding needs none.

| Step | What dispatches itself | Advance condition |
|---|---|---|
| Brief | Director records audience, purpose, constraints and resource budget in `CONCEPT.md`; does not commission content yet | Objective and constraints are explicit; no compulsory reference artists/styles |
| Capability choice | Tool Scout or Director records live media capabilities in `reports/tool-probe.md`; Director decides modality; does not generate | Separate available, permitted, verified and chosen modalities; choose for the story, not a hardcoded tool priority |
| Research and script | Dispatch Screenwriter (+ Researcher **only when `kind` is scientific/educational and facts are load-bearing**; otherwise no Researcher); Director does not write the script in the main thread | `SCRIPT.md` exists; claims are sourced or explicitly labelled model-knowledge-unverified when `kind` requires auditing; progression and reading time work for the audience |
| Design exploration | Dispatch 1–2 Art Directors when design space is genuinely open; otherwise 1 | Subject-led visual intent articulated; differences concern visual storytelling, not only palette |
| Proof and selection | Render styleframes and dispatch the reviewer only if the comparison is blocked or the visual risk is material; Director selects | Selection cites rendered evidence and tradeoffs, not majority vote or proposal length |
| Shot planning | Director writes `reports/shotlist.md`; skip if brief is a single shot (record skip in one line) | Covers the script without inventing fixed shots/components/layouts |
| Build and compile | Dispatch Builders per disjoint file domain (parallel when profitable); Director integrates and runs S1–S5 | All in scope implement; real exit codes captured |
| Rendered review | 1 fresh Visual Reviewer when the render is novel / risky / adjudication-blocking; Director may self-check if a skip is logged | Reviewed artifacts passed; every defect has an owner |
| Quality refinement | Director identifies the weakest passage; dispatch one bounded refinement for that passage only; record pass/fail | Before/after compared; improvement may REMOVE text/texture/motion/objects |
| Final review and delivery | 1 fresh reviewer (T1/T2); T3 = self-review, labelled | All unresolved blockers are noted as such in `DELIVERY.md`; no silent pass |

Design exploration is scaled to uncertainty and budget. For a new visual
problem, compare two treatments; for a small revision, one justified treatment
may suffice. T3 may develop alternatives sequentially but must not claim
independent authors. Do not force one low-density and one high-density design.
Do not merge two weak proposals automatically: choose, revise or reject based
on rendered proofs. A coherent winner may be better than combining both.

### Zero-template quality contract

`DESIGN.md` defines THIS project's visual intention and observable criteria:
what the viewer should notice, understand and feel; visual hierarchy; temporal
rhythm; why this treatment suits the subject; and which failure would undermine
it. References can clarify a decision but are optional, not a quota.

There are no universal requirements for textures, gradients, shadows, depth
layers, font-weight ratios, subject coverage, palettes, component counts or
ornament. Flat, monochrome, typographic, photoreal and deliberately static
approaches are all valid. More detail is not necessarily better. Review the
render at delivery size and inspect motion as well as isolated frames.

Require a project-specific overall-quality item in `spec.checklist`, alongside
comprehension and technical checks — and `factual accuracy` **only when `kind`
is scientific or educational** (for narrative/mood films, storytelling and
calibration replace the fact check; don't bolt on a science audit the brief
never asked for). Evaluate it with visible evidence, not by counting
decorative techniques. A metric is a diagnostic, not an aesthetic objective.
Do not add particles, camera drift
or breathing solely to satisfy freeze detection. For intentional holds,
document the intent before opting out via `frame_freeze`; record the skip,
check duration/readability, and never describe that test as passed.

### Bounded communication and independent decisions

- Script reviewer ↔ writer, factual reviewer ↔ researcher/writer, design
  reviewer ↔ design authors: ask for evidence and allow accept/object replies.
- The factual-reviewer exchange runs **only for `kind ∈ {scientific, educational}`**;
  the narrative-reviewer runs for all kinds.
- A design comparison allows each author one response round. Other local
  review/fix exchanges allow at most two rounds; factual clarification one.
- **Fix verification re-renders the whole element, not the fix point.**
  Verifying only the changed property invites silent regressions elsewhere in
  the same element (measured: a typography fix that swapped an SVG-invalid
  HTML tag destroyed every CJK heading in the frame while the fixed property
  itself rendered perfectly — both author and reviewer missed it checking
  only the fix). After any fix, the verifier re-checks the full element
  (text present and intact, layering, positioning) on the re-rendered frame.
- Rendered reviewer routes findings to the original owner within the existing
  write domain. T1 sends directly; T2 relays through Director; T3 records self-review.
- First reviews use brief, criteria and artifacts, not the author's defensive
  account or previous verdict. AFTER the independent report, discussion may
  resolve questions. Final review receives current artifacts and required
  intent/constraints, not lobbying or a preselected verdict.
- Never invent an author's answer, impersonate another agent or call a quoted
  proposal an actual exchange. Reuse an instance only through the real session
  parameter; placing an ID in message text does not resume it.
- Reviewer reports pass / needs-work / blocked with evidence; Director selects
  direction and records accept/reject reasons. Neither can erase unresolved
  evidence by vote. Reviewers read project files but write only their report
  when authorized (otherwise return text for Director to save).

### Budgets, provenance and truthful reporting

- Default local rework budget: two rounds per issue; at most three build/render
  attempts for a production milestone unless the user sets another budget.
  These are shared counters, not fresh allowances per role. Exhaustion means
  stop and report; renaming a task or adding a reviewer does not reset them.
- Preserve project assets and user edits. Production does not edit the engine.
  Compare source snapshots or scoped diffs before/after, excluding generated
  outputs, caches and dependencies; report differences rather than reverting
  unrelated user work. This rule does not prohibit explicitly requested engine maintenance.
- Tool availability is not permission to spend. Respect explicit cost/privacy
  constraints; otherwise establish a budget before paid calls. Do not erase
  capability declarations to simulate absent tools or claim code is generated media.
- Keep raw findings, actual replies, dispatch IDs, artifact versions and gate
  results in `reports/`. Reports are evidence, not a tamper-proof script ledger.
- Check gate exit codes directly (or a wrapper preserving the exact return code),
  never a pipe/filter's exit code. A stale render invalidates its visual review.
- Delivery states actual tier(s), sources, costs/calls, evidence inspected,
  self-review/independent-review status, skips, unresolved issues and limitations.
  Never claim full playback when only sampling stills, or model use without calls.
- For comparisons, distinguish an end-to-end workflow comparison (same brief,
  tools/model/budget; designs may differ) from a transport-only experiment
  (freeze script/design/assets too). Use fresh sessions and blind review.
  Revisions informed by a previous failure are NOT independent A/B trials;
  a single pair supports observations, not a causal or statistical claim.

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
  `verify-rig` checks alignment against its configured tolerance (inspect CLI defaults).
- **`poses`** — frame-switched sprite swaps on an `ai` layer.
- **`spring`** — secondary motion (inertia lag/overshoot) driven by a
  channel of the parent.
- **`verify-blocking`** — co-planar characters must not overlap in the same
  horizontal lane (lane separation + max overlap).
- **`verify-combat`** — weapon-tip/target contact on the `tracks.events`
  `kind: "contact"` frames.
- **`verify-continuity`** — geometric scene handoffs: background
  continuity and character position continuity against configured tolerances between shots.

Acting decisions (which pose, when, with what spring values) are authored in
the spec per video; the engine verifies geometry, not performance.

## Authoring pitfalls (measured on real renders)

1. **`z` is unique per shot** — `validate` rejects duplicates; stacking is
   undefined without it.
2. **Still shots may trigger motion/freeze gates** — distinguish intentional
   holds from rendering failures; use documented opt-outs for intended stills,
   not meaningless motion to make a metric green.
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
11. **Freeze detection is not an exact duplicate-frame test.** It uses a
   frame-wide difference threshold, so sparse low-contrast motion may be flagged.
   Inspect actual frames and the intended motion before changing anything.
   Do not prescribe particle counts or motion amplitudes for all projects.
12. **A color ratio is a whole-shot statistic, not proof of a narrative error.**
   A zero median may simply mean a color appears in fewer than half the frames.
   Check per-beat renders and color matching before changing art or thresholds.
13. **Design review cannot replace rendered review.** Store full-size frames
   where the reviewer can actually read them; check transitions and timing too.
   If image access fails, record blocked evidence, not an invented visual verdict.
14. **Gates measure "not broken", never "alive" — transform motion can pass
    every gate and still read dead.** Camera moves and parallax that are too
    small for the subject, the contrast and the shot length can satisfy the
    motion and freeze gates while a viewer sees a still frame (two measured
    cases: a 5% zoom over 18 s and a 7% two-plane parallax, both shipped
    "green and dead"). These are cases, not a universal percentage: there is
    no threshold that applies to every shot, because legibility depends on
    how much of the frame moves, how much contrast it has and how long the
    viewer has. Judge the motion with a short rendered proof against the
    intended experience — either make the change perceptible and add change
    points at beat boundaries, or own the stillness explicitly
    (`frame_freeze` + documented intent). If the aliveness still cannot be
    reached with transforms, change the motion approach or the asset
    modality rather than scaling the same transform harder.
15. **S2 re-encodes every clip to yuv420p — alpha does not survive that
    path.** A transparent `video` layer does not exist in this engine's
    current clip pipeline (the container format is the limitation, not
    video itself). Layered compositing over moving footage uses static RGBA
    stills (see 16) or opaque rectangular planes; plan the occlusion order
    around what the clip path cannot carry.
16. **`mixBlendMode` is trapped inside the anim wrapper's stacking context.**
    Any animated layer's transform creates a new stacking context, so a
    `blend: "screen"` layer composites against that context's backdrop —
    effectively transparent black — not against the layers below it (measured:
    a screen-blended cup with a black top silently occluded the footage
    behind it). For per-pixel transparency use an RGBA PNG with `normal`
    blend (`write_png_rgba` in `core/media/png.py`); note the derived-asset
    workflow: mask alpha in a copy of a frozen still (e.g. subject cutout
    with feathered edges) and register it as its own manifest asset. RGBA is
    a transparency mechanism, not an equivalent of `screen`/additive
    blending; verify the composited result visually.
