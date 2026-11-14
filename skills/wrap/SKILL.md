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
| `z` | every layer | Strictly unique integer per layer within a shot (`validate` rejects duplicate `z` values with `"duplicate z"`). Controls back-to-front stacking order (`0, 1, 2, ...`). |
| `anim` | any layer | Keyframe channels `x/y/scale/opacity/rotate/flipX/depth`; frames strictly increasing; optional ease per keyframe (`linear/in/out/inout/snap/overshoot/step`) on the segment END. Entrances, camera moves, turnarounds (`flipX: 0\|1`), exits — all data. |
| `parent` / `pivot` / `flipX` | any layer | Hierarchical 2D parenting across any layer type (`ai`, `code`, `text`, `hud`, `card`, `video`): child inherits its ancestor chain's transforms (`x/y/scale/rotate/flipX/opacity` + sympathetic `shudder` gait) before applying its own `rotate` and `flipX` around `pivot: [px, py]` (defaults to `[rect[0] + rect[2]/2, rect[1] + rect[3]/2]`; for left-aligned `text` layers without an explicit `pivot`, `flipX` mirrors around the rendered text content's own center `fit-content` so it does not jump across a wide `rect`). |
| `motion` | `ai` / `video` / `code` (`grid`\|`dots`) | `{"type": "geometric", "zoom": [z0, z1]}` continuous camera push-in/pull-out. **Pure still-image shots without motion will fail the S4 `motion` (`changed_pixel_ratio`) and `freeze` (`freezedetect`) gates** — always pair static plates with `motion.zoom` (e.g. `[1.0, 1.08]`), `anim` keyframes, or an active `field`/`path`/`video` layer. |
| `gait` / `spring` / `poses` | ai layer | Procedural locomotion/tremor (`mode: puppet\|walk\|float\|shudder`, `freq`, `bob`, `sway`, `range`), 2nd-order inertia (`omega`, `zeta`, `coupling`, `channel`, `driverChannel`, `maxAccel`), and frame-switched sprite swaps (`[{frame, asset}]`, e.g. swapping a weapon arm to a bare arm during kowtowing/agony). |
| `cutout` / `translucent` / `clipRect` | ai layer | `cutout: true` keys `keyColor` to alpha with `fit: "contain"`; `translucent: true` renders warm backlit oxhide luminance + dynamic penumbra (`depth`, `shadowColor`); `clipRect: [x,y,w,h]` masks scrolling backdrops inside a proscenium aperture. |
| `field` (code draw) | `params` | Parameterized particle field: `count, seed, colors, dir, spread, speed, size, glow`. Atmosphere on demand, not baked in. |
| `path` (code draw) | `params` | SVG path with `reveal` (dash draw-on) or `flow` (drifting dashes), `stroke/width/opacity`. Guide lines, orbits, energy tracks (forbidden as wireframe circles on shadow-puppet stages). |
| `captions` (code draw) | `params` | Subtitle track: `items` = list of `{frame, text, hl?, size?}` — each appears from its own `frame` onward; `hl` marks the substring to highlight; `size` (px) and `hlColor` set the styling; `sync-audio` piecewise-warps all layer keyframes to match synthesized TTS clause timings. |
| `vibe: false` | spec root | Opts out of the baked vertical ambience (particle rain, scanline, blueprint grid). Bring your own atmosphere via layers. |
| `plate: false` | ai layer | Full-bleed presentation — no card chrome (border/rounding/vignette). |
| `color` | text layer | Solid color + scrim instead of the default white-cyan gradient. |
| `fontSize` / `fontWeight` / `subtext` | text layer | Title size (px), weight (`string` or number), and the smaller line under the title. |
| `playbackRate` | video layer | Clip speed multiplier (positive number). `1` is real time; `0.5` is half speed (S4 `changed_pixel_ratio` automatically deduplicates short cadence frame holds `<= 6` frames so slow-motion clips are measured on true visual transitions). When `muted: false`, the clip's own audio is time-stretched to match (`atempo`, pitch preserved; multi-stage for rates outside `[0.5, 100]`, loops repeat the window before stretching). |
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
   **Assets and audio tracks are bit-exact reproducible**: a synthesized TTS
   track is frozen to `assets/tts_{hash}.wav` (keyed by voice + rate + text),
   so the same words always yield the same bytes and the same loudness.
   **A rendered mp4 is byte-exact reproducible only for shots WITHOUT text
   layers** — Chromium's font antialiasing rounds a few pixels differently
   between runs (measured: 4 of 150 frames differ by <8/255), so a shot with
   text guarantees the same *content*, not the same *SHA256*.
2. **Zero-dependency pixel & audio metrics** — raw-video byte math, not ffmpeg `geq`.
3. **Fail-fast keying purity & aspect-ratio preservation (S2)** — 8px perimeter purity
   >= 98% before render spend; subregion scaling always preserves aspect ratio.
4. **Broadcast audio** — TTS voiceover (voice/rate resolved from `style.json`, spec, or environment) with mastering chain
   (highpass/EQ/compand) + `loudnorm` to -16 LUFS; ambient = 4-harmonic drone.
5. **Narrative timeline contract** — structured `beat` + non-empty `reason` per shot;
   talk alone is never completed state, only verified `build/` artifacts count.
6. **Honest gating** — deterministic gates say "not broken"; the S5 judge says
   "looks right and says something". Neither substitutes for the other.
7. **The renderer may not lead the contract** — every draw the renderer has an
   explicit branch for must be in the contract's `DRAWS`. The safe direction
   (the contract may not name a draw the renderer cannot draw) is checked by
   `tests/contract/test_draw_contract.py`; the reverse is checked by
   `tests/contract/test_contract_weakening.py`, because narrowing the contract
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

## Multi-Shot Episode Recipe (Image → Clip → Seam → Film)

The vocabulary above is per-shot. This is how it becomes a film: how one
image becomes a clip, how two clips become a seam, and how a seam becomes an
assembled episode.

### The two continuity modes

| Mode | How | Continuity | Cost |
|---|---|---|---|
| **Asset seam** | Shot k's `last_frame` asset IS shot k+1's `first_frame` asset | The model is told to end on image B and to start on image B — visually seamless, but the model's endpoint is an APPROXIMATION of B | one image per seam |
| **Frame seam** | `pipeline.py extract-frame` freezes shot k's rendered tail as an asset; shot k+1 names it as `first_frame` | Exact — shot k+1 starts on the actual pixels shot k ended on | no extra image |

Frame seam is the truthful one when the cut must not show. Asset seam is the
cheap one when a shared look is enough.

### The manifest is project-scoped

`manifest.json` lives at the PROJECT root (`POSTER_ROOT`), not per shot. A
shot can therefore reference an asset another shot generated — that is how a
cross-shot seam works at all.

It also means the ORDER of the run matters: **shot k must be GENERATED before
shot k+1's S1 runs**, or S1 will not find the asset and will say so.

### The workflow

```bash
# 1. generate + render shot k (this is where the model call happens)
python3 pipeline.py run --spec spec/shot-01.poster.json

# 2. (frame seam only) freeze shot k's tail as an asset
python3 pipeline.py extract-frame --video build/shot-01.mp4 --name shot-01-tail --at last

# 3. generate + render shot k+1 — its first_frame now resolves
python3 pipeline.py run --spec spec/shot-02.poster.json

# 4. assemble
python3 pipeline.py concat --timeline spec/timeline.json --output build/full.mp4
```

A timeline is a project-level list of shots, each a spec path with a beat and
a reason (`beat` ∈ hook / development / climax / resolution / transition /
intro / outro):

```json
{
  "id": "my-episode",
  "shots": [
    {"spec": "spec/shot-01.poster.json", "beat": "hook", "reason": "the one image that earns the rest"},
    {"spec": "spec/shot-02.poster.json", "beat": "resolution", "reason": "the same world, one beat later"}
  ]
}
```

`concat` assembles what exists and rebuilds what is missing from S1/S2/S3/S4
— but it will **not** generate assets for you: a missing asset costs a model
call, so it stops and names the `generate` command to run instead.

### One command instead of four: `run --timeline`

The recipe above is the contract; `run --timeline` executes it. It renders the
shots IN ORDER — so a shot k+1 whose `first_frame` names shot k's tail finds
that asset — freezes the seams as it goes, then assembles and runs the
full-video gates:

```bash
python3 pipeline.py run --timeline spec/timeline.json --output build/my-episode.mp4
```

The seam is a NAME, not a flag: if the next shot references an asset called
`<something>-tail` and nothing is frozen under that name yet, the current
shot's rendered last frame is frozen under it (registered in the manifest like
any other asset, `source: "extracted"`). The frame is taken between shot k's
render and shot k+1's S1 — the only moment it can exist.

`--fixture` rehearses the whole film for free (placeholder assets, no model
call); `--force` re-generates assets instead of reusing the frozen ones.

### What the pipeline will NOT do for you

- It does not invent a seam. Shot k+1 must still NAME the tail asset
  (`"first_frame": "shot-01-tail"`); `run --timeline` freezes the frame under
  that name, it does not decide that a seam belongs there.
- It does not stitch one shot's tail onto the next shot's head pixel-wise. The
  seam is the model STARTING ON shot k's last frame — a new clip, not a
  cut-and-paste.
- It does not re-order shots. The timeline order is the film order.
- It does not close the visual audit. `run --timeline` renders and gates; the
  S5 judge verdict is still yours to give, shot by shot.

## Asset Transport (S1) & Environment-Adaptive Model Discovery

`stages/01_generate.py` calls the `mcode-tools connector` where available. On
machines without it, keep the manifest contract and substitute the transport:
gradio_client -> HF Spaces (watch for webp bytes masquerading as .png — convert to
true PNG before registering, data-URL MIME is not sniffed by Chromium), or
public-domain sources (NASA SDO etc.) registered with `source=` and `credit=`.
ZeroGPU anonymous quota is tiny and policy-drifts; a free account token is the
reliable channel.

### Never Hardcode Model IDs — Inspect the Environment First

Do **not** hardcode specific image, video, or TTS model identifiers in skills or
authoring templates. Available models and parameter schemas are discovered from
the runtime environment:

1. **Connector Schema Inspection**: Run `mcode-tools connector list` and
   `mcode-tools connector tool <tool_name>` to inspect the active backend's
   supported models, durations, resolutions, and reference capabilities.
2. **Environment & Style Configuration**: `core/generation/models.py` and `stages/01_generate.py`
   resolve available model capability matrices and defaults dynamically via:
   - `POSTER_MODELS_JSON` — JSON string or path overriding/extending `VIDEO_MODELS`
     capability matrix (`durations`, `resolutions`, `audio`, `input_image`,
     `last_frame_image`, `reference_media`).
   - `POSTER_VIDEO_MODEL` / `style.json["videoModel"]` — default video generation
     model when a `video` layer omits `"model"`.
   - `POSTER_IMAGE_AREA` / `style.json["area"]` (or `style.json["resolution"]`) —
     default image size tier (`1K` | `2K` | `4K`).

   A malformed or incomplete override is **reported on stderr and ignored** —
   the built-in catalog stays in place instead of taking the engine down. An
   override for a NEW model must carry `min_dur`, `max_dur` and `resolutions`;
   a partial one is refused with a warning rather than producing an entry the
   validator cannot read. If `POSTER_VIDEO_MODEL` names a model that is not in
   the catalog, `validate` reports it instead of failing later inside the
   transport.
3. **Capability-Driven Selection (Not Name-Driven)**: Choose a model from the
   `core.generation.models.VIDEO_MODELS` catalog based on the shot's functional needs:
   - **Fast iteration / keyframe-anchored motion**: pick a low-latency model that
     supports `input_image` (`first_frame`) and optional `last_frame`.
   - **High-fidelity / multi-modal reference**: when a shot requires
     `reference_images`, pick a model where
     `video_supports_reference_media(model)` is `True`.
     (`reference_videos` / `reference_audios` are **refused** by `validate` — S1
     has no way to resolve a video or audio source, so accepting them would
     silently drop the reference and hand back a text-to-video clip.)
   - **Silent B-roll under TTS narration**: any model works with `"muted": true`;
     models without native audio (`video_has_audio(model) == False`) are
     lightweight choices when TTS owns the soundtrack.
   - **Clip length**: `video_allowed_durations(model)` returns the discrete set a
     model accepts, or `None` when any integer in its range works.

### Native Generation Backends

The connector exposes native image and video generation. The pipeline is the
consumer; these are the backends it can drive.

**Image** — `connector__matrix__generate_image` (text-to-image, plus
image-to-image via `reference_images: [{"url": ...}]`). Takes `aspect_ratio`
(1:1 / 16:9 / 9:16 / 4:3 / 3:4 / 21:9) and `area` (1K / 2K / 4K). S1 derives
`aspect_ratio` from the spec canvas, so a 1080x1920 vertical shot asks for a
vertical plate. The generator may return JPEG/WebP regardless of the requested
format — S1 normalizes every download to a true PNG before freezing it.

**Video** — `connector__matrix__submit_video_generation` +
`connector__matrix__query_video_generation`. Asynchronous: submit returns a
`task_id`, the task is polled until it succeeds, then the clip is downloaded
and frozen like any other asset. A video layer may also declare `first_frame`
(or `input_asset` / `input_image`), `last_frame`, `reference_type`, and
`reference_images` — S1 resolves any static `code` layer (`grid`/`dots`),
`ai` layer asset, or manual `manifest` asset through the same upload path and
sets `ratio: "adaptive"`.

**Clip length is not a free number.** Some backends accept a DISCRETE set of
durations rather than a range — Hailuo-2.3 takes 6 or 10 seconds and nothing
between, and 1080P caps it at 6. `validate` rejects a duration the backend
would refuse, and S1 rounds the shot length UP to an accepted value (a 7s
shot asks for 10s and is trimmed back). Never hardcode a duration a model
cannot express; leave `"duration"` out and let the pipeline pick.

**Model capability boundaries.** Not every model can do every reference mode,
and the difference is paid for, not reported after the fact:

| Mode | MiniMax-H3 | MiniMax-H3-Max | MiniMax-Hailuo-2.3 |
|---|---|---|---|
| text-to-video | ✅ | ✅ | ✅ |
| `first_frame` (image → video) | ✅ | ✅ | ✅ |
| `last_frame` (tail keyframe) | ✅ | ✅ | ❌ |
| `reference_images` (multi-reference) | ✅ 1–9 | ❌ | ❌ |
| `reference_type: "subject"` | ❌ | ❌ | ❌ **fails upstream AFTER billing** |
| native audio track | ✅ | ✅ | ❌ silent (needs TTS on top) |
| duration | 4–15s | 5–15s | **6 or 10s only** (1080P → 6s) |
| resolution | 768P / 2K | 480P / 768P | 768P / 1080P |

`reference_images` is **H3-only**; asking H3-Max or Hailuo for it is caught by
`validate` before the call, not after. The one trap left is `subject`: the
schema used to advertise it for Hailuo, the upstream service fails it AFTER
billing, so it is now listed under `unsupported_reference_types` in
`core/generation/models.py` and refused in `validate`.

**Audio ownership is exclusive — and voiceover is completely optional.**
The pipeline supports both narrative documentary explainers (with TTS narration)
and music-first short-video content (Douyin / TikTok visual cards + soundtrack,
opera percussion dances, trailers, or pure silent shots).

- **TTS owns the audio**: The video layer is muted (`"muted": true`) and
  `audio.voiceover` drives the soundtrack (+ optional ambient bed `audio.bgm`).
  Synthesized TTS tracks are automatically frozen to `assets/tts_{hash}.wav` as
  deterministic assets, guaranteeing bit-exact reproducibility across runs.
- **Pure BGM / music-first (no voiceover)**: Omit `audio.voiceover` and provide
  `audio: {"bgm": "ambient"}` (or `"opera"`, `"shadow_puppet"`, or any external
  audio file such as `"assets/douyin_bgm.mp3"`). The BGM is mastered at full
  volume to the exact -16 LUFS broadcast target. S4 automatically exempts
  speech-band frequency checks for voiceover-free shots (`> -45 dB` non-silent
  and in-band LUFS passes). Multi-shot cuts can pass `audio.bgmOffset: 3.5` to
  slice subsequent windows of a shared song with micro-fade protection.
  `python3 pipeline.py sync-audio` automatically paces `captions` across the
  shot's frames according to natural reading cadence even without voiceover.
- **The clip owns the audio**: set `"muted": false` on the video layer and
  leave `audio.voiceover` and `audio.bgm` empty for that shot. The clip's own
  track is mastered to -16 LUFS.
- **Pure silent shot**: Leave `audio` empty (or `"muted": true` video layer);
  a compliant 44100 Hz stereo silent track is generated so concatenation is
  preserved — the mp4 always carries an audio stream, so a silent shot can sit
  beside a narrated one in the same timeline. S4 exempts it from the
  speech/loudness gates (the shot is silent *by design*), and the full-video
  `loudness_jump` gate ignores that segment. Measured: a silent shot lands at
  -91 dB and contributes 0.0 LU to the jump budget.

**Measured anchors.** A pure-BGM shot with no voiceover masters to **exactly
-16.0 LUFS** (the two-pass loudnorm has no speech to fight with); a mixed
voiceover+bgm shot lands in [-16, -15]. A silent shot measures -91 dB. Treat
these as the values you should see — a BGM-only shot outside [-17, -15] means
the mastering chain drifted, not that the shot is wrong.

Mixing TTS voiceover and unmuted video audio is a bug — S3 rejects the spec with
a readable "audio conflict" error, and S4 audio gates would flag the overlap.

A clip's native track and pure BGM tracks are mastered to the same -16 LUFS target
as the TTS chain, so every shot sounds consistent whichever track owns it. The audio
gates run whenever the *rendered* mp4 carries a track — not only when the spec declares
an `audio` block — so every soundtrack mode is verified.

## Layer Types & LLM-Driven Composable Modalities

1. **`ai`** — prepared image or articulated puppet/prop layer; `blend`, `keyColor`, `cutout`, `translucent`, `depth`, `shadowColor`, `flipX`, `parent`, `pivot`, `joint` (`[sx, sy]`), `socket` (`[sx, sy]`), `partScale`, `snap` (`"socket"`), `kit` (`{type, joint, socket}`), `role` (`humanoid | quadruped | mech | prop | backdrop`), `input_asset`, `reference_images` (`1..16` assets/layers for multi-image fusion), `gait` (`{mode: puppet|walk|float|shudder, freq, bob, sway, range}`), `spring` (`{omega, zeta, coupling, channel, driverChannel, maxAccel}`), `poses` (`[{frame, asset}]`), `controlRod` (`boolean`), `rodAnchor` (`[rx, ry]`), `rodAnchors` (`[[rx, ry], ...]`), `clipRect`, `motion.zoom`, `fit`, `plate`.
2. **`video`** — prepared video layer; `asset` (an mp4), `fit`, `trim`, `loop`,
   `muted`, `motion.zoom`, `plate`, plus optional `first_frame` / `last_frame` /
   `reference_images`. No `keyColor`: edge keying is a still-image
   concept, so a video layer skips the purity gate and is scaled to cover its
   rect instead. The clip is re-encoded at the shot's frame rate in S2 — a
   source clip at a different rate would otherwise loop over a window longer
   than itself and freeze on its last frame.
3. **`code`** — `grid | dots | bar | field | path | captions` (parameterized primitives)
   plus legacy hero scenes (see vocabulary section). `grid` and `dots` are
   prepared as an image, so they take `motion.zoom` (a camera push-in on the
   background) and can also feed a `video` layer's `first_frame`; every other
   draw scales through the `anim` `scale` channel.
4. **`text`** — title/subtitle, spring or keyframe entrance, gradient or solid `color`.
5. **`hud`** — `badge | telemetry | equalizer | progress`. Decorative:
   use deliberately, not by default on every shot.
6. **`card`** — `capsule | formula | quote`.
7. **`component`** — custom project-level React component; `component` (registered in `<project>/remotion-custom.tsx` via `CUSTOM_COMPONENTS`), `rect`, `z`, `props` (arbitrary object bag passed to the component).

### LLM-Driven Modality Composition (Free Combination Over Fixed Paths)

Because `code`, `ai`, and `video` layers share a unified manifest and cross-feeding
interface (`input_asset`, `first_frame`, `last_frame`, `reference_images`), **there
are no mutually exclusive "paths"**. The authoring LLM decides how to combine
modalities per shot (and per layer) so each medium plays to its strength:

| Modality | Core Strength | Weaknesses When Used Alone | How to Combine with Other Modalities |
|---|---|---|---|
| **`code` (Procedural / Canvas / SVG)** | Exact mathematical geometry, typography, grids (`grid`/`dots`), particles (`field`), trajectories (`path`), frame-accurate `captions` | Cannot synthesize photorealistic textures, organic characters, or fluid 3D camera parallax | Use as crisp foreground overlays (`path`, `captions`, `card`, `hud`) on top of `ai`/`video`, OR pre-render `grid`/`dots` as the structural `first_frame` anchor of a `video` layer |
| **`ai` (Still Plates / Cutouts / 2D Skeletal Rigs)** | High-resolution art direction, style-locked image-to-image (`input_asset`), deterministic 2D bone/IK acting (`parent`/`pivot`/`gait`/`spring`/`poses`), zero temporal morphing | Full-scene 3D fluid motion or complex atmospheric fluid dynamics (fire, waves, crowds) require heavy rigging if done purely in 2D | Use `ai` for foreground articulated characters (`cutout: true`) or scrolling stage plates (`clipRect`), while pairing with `code` particles (`field`) or a `video` atmospheric backdrop; or feed an `ai` plate into a `video` layer's `first_frame` / `last_frame` / `reference_images` |
| **`video` (Generative Video Clips)** | Rich 3D camera parallax, continuous natural fluid/crowd/lighting motion, optional native ambience/SFX | Unconstrained text-to-video drifts in palette/layout and mangles exact text or fine martial choreography | Anchor the `video` layer with `first_frame` / `last_frame` / `reference_images` from an `ai` plate or `code` layer (`grid`/`dots`), then composite sharp `ai` character cutouts, `code` diagrams, and `text`/`captions` on higher `z` layers |

**Decision checklist for the LLM when designing each shot:**
1. **What needs frame-exact precision or legible text?** → Put it in `code` (`path`, `captions`), `text`, `card`, or `hud` layers.
2. **What needs repeatable character acting, martial contact, or shadow-puppet craft?** → Put it in `ai` layers (single plate or multi-part `parent`/`pivot` skeletal rig) so keyframes and `sync-audio` control every beat deterministically.
3. **What needs organic environmental motion, 3D camera depth, or cinematic transitions?** → Put it in a `video` layer, and anchor its composition by feeding a `code` or `ai` asset into `first_frame` / `last_frame` / `reference_images`.
4. **Can they stack in the same shot?** → Yes: e.g., `z: 0` generative `video` sky/water (anchored by an `ai` style plate) + `z: 1..2` scrolling `ai` stage architecture + `z: 10..30` articulated `ai` character rigs + `z: 40` `code` (`field` embers + `captions`).

## Quick Start

```bash
python3 pipeline.py init-shot my-shot                      # schema skeleton + design hints (no layout)
python3 pipeline.py run --spec spec/my-shot.poster.json --fixture   # free rehearsal: placeholder assets, no model call
python3 pipeline.py run --spec spec/my-shot.poster.json    # S1->S5 (visual verdict pending)
python3 pipeline.py run --timeline spec/my-timeline.json --output build/my-episode.mp4   # the whole film: in order, seams frozen, assembled, gated
python3 pipeline.py judge --spec spec/my-shot.poster.json --verdict pass --notes "..."   # close S5
python3 pipeline.py concat --timeline spec/my-timeline.json --output build/full.mp4      # + full-video gates
python3 pipeline.py sync-audio --spec spec/my-shot.poster.json      # piecewise clause-anchored TTS audio/keyframe sync
python3 pipeline.py verify-rig --spec spec/my-shot.poster.json      # verify 2D skeletal joint/socket alignment
python3 pipeline.py verify-blocking --spec spec/my-shot.poster.json --max-overlap 0  # verify zero co-planar torso overlap
python3 pipeline.py verify-combat --spec spec/my-shot.poster.json   # verify weapon-tip contact on punch frames
python3 pipeline.py verify-continuity --timeline spec/my-timeline.json  # verify multi-scene scroll transitions & acting sync
python3 pipeline.py test                                   # regression suite
```

`--fixture` writes deterministic placeholder assets instead of calling a
(billed) model — rehearse the whole pipeline for free before spending. The
placeholders are registered in the ledger, so a later real run reuses them; S1
says so when it does, and `--force` makes it generate the real asset instead.
A placeholder is not a deliverable — never ship one.

### Using a generated video clip (standalone or anchored by code/AI assets)

A video layer is declared in the spec like any other layer (omitting `model`
uses the environment/style default, or set `model` to any model supported by
the active environment):

```json
{
  "id": "hero-clip",
  "type": "video",
  "asset": "push-in-clip",
  "rect": [0, 0, 1080, 1920],
  "z": 0,
  "plate": false,
  "first_frame": "hero-plate",
  "duration": 6,
  "muted": true
}
```

```bash
python3 pipeline.py run --spec spec/my-shot.poster.json
```

What to expect:

- **S1 is the slow step.** It submits the clip, polls until the backend model
  finishes, downloads it and freezes it by sha256. Fast iteration models return
  quickly (~20s); high-fidelity multimodal models take longer. The run is billed
  like any other generation call.
- **The clip is frozen after the first run.** A second `run` reuses the
  recorded asset — it does not generate a new clip. Pass `--force` to S1
  explicitly if you really want a new one.
- **`model` / `duration` / `resolution` / `ratio` / reference capabilities are
  validated before the call.** An unknown model, a duration outside the model's
  range, or an unsupported reference field (`first_frame`, `last_frame`,
  `reference_images`) is rejected by `python3 pipeline.py validate`, so a
  mismatch never turns into a paid call that fails.
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
- **Waiting.** S1 polls the backend until it finishes and prints each poll's
  task status, so a long wait is visible rather than silent.

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

## 2D Skeletal Rigging, IK & Co-Planar Stage Blocking

When a shot animates multi-part 2D characters or shadow-puppet assemblies, the
engine provides a generic skeletal parenting, socket calibration, combat-contact,
and co-planar stage-blocking subsystem (`core/rig/`, public API: `core.rig`):

- **Hierarchical Parenting & Pin-Joint Sockets** — A child layer declares
  `parent` (parent layer ID), `joint` (`[jx, jy]` in child asset pixels), and
  `pivot` (`[px, py]` in canvas coordinates), while the parent layer declares
  receiving `sockets` (`{"arm-front": [sx, sy], ...}`). Use
  `python3 pipeline.py snap-joint` to compute exact canvas `rect` and `pivot`,
  and `python3 pipeline.py verify-rig --spec <spec>` to verify sub-pixel socket
  alignment (`delta <= 2px`).
- **Articulated Full-Body Rigs & Props** — Every active humanoid character in a
  2D scene must be rigged into independent articulated parts (`torso/body`,
  `head/plume`, `arm-front`, `arm-back`, `leg-front`, `leg-back`) rather than
  sliding as a rigid single-PNG cutout. Handheld props (canes, staffs, baskets,
  weapons) must be preserved in full within their limb/prop layer (`pad >= 24px`)
  and never cropped mid-shaft.
- **Secondary Spring-Damper Physics & Aperture Depth** — Child layers may declare
  `spring: {"omega": 18.0, "zeta": 0.25, "coupling": 0.45, "channel": "rotate", "driverChannel": "rotate", "maxAccel": 4500.0}` (`omega` in [1, 120], `zeta` in [0.01, 2.0], `coupling` in [-5, 5]) for
  automatic inertia lag/overshoot driven by parent acceleration, and `depth`
  (`[0, 1]`) for dynamic shadow-screen penumbra blur (`shadowColor` customizable).
- **Physical Combat Contact (`verify-combat`)** — Declare `combat: {"attacker":
  "...", "weapon": "...", "target": "..."}` (or pass CLI flags) and run
  `python3 pipeline.py verify-combat --spec <spec>` to verify weapon-tip
  collision against target hitboxes on all `punches` frames.
- **Co-Planar Non-Overlapping Stage Blocking (`verify-blocking`)** — Because 2D
  cutout and shadow-puppet characters share a single translucent projection
  plane, two characters occupying the same horizontal X interval merge into an
  unreadable silhouette. Partition the stage into distinct horizontal lanes
  (e.g., Left Lane / Center Martial Lane / Right Lane), use push-pull yielding
  when a character lunges, and gate every multi-character shot with
  `python3 pipeline.py verify-blocking --spec <spec> --max-overlap 0`.
- **Multi-Scene Push-Pull Scrolling Transitions & Narrative Props (`verify-continuity`)** —
  Multi-scene stories must never feel like independent static backdrops stitched
  together by abrupt hard cuts:
  1. **Frame-Within-Frame Seamless Scrolling Scenery (`推拉换景 / 无缝长卷`)**:
     Keep the outer stage proscenium frame fixed at `z: 0`, and place inner
     scenery scroll plates (`role: "backdrop"`, clipped to the inner aperture
     via `clipRect`) at `z: 1..2`. Inner scroll assets must exclude outer wooden
     pillars/tassels and horizontally feather/mirror-blend their left & right
     edges (`>= 96px`) to a shared horizon palette so zero vertical seam line or
     pillar crosses the stage when `anim.x` slides (`0 -> -W` paired with `+W -> 0`).
  2. **Seamless Cross-Shot Backdrop & Character Coordinate Handoff (`跨幕同景与角色坐标咬合`)**:
     When Shot $k$ scrolls into a new scenery plate at its tail, Shot $k+1$ must
     open on that exact same scenery plate (`end_backdrop == next_start_backdrop`).
     Furthermore, any character visible on stage at both the end of Shot $k$ and
     frame `0` of Shot $k+1$ must preserve their exact canvas `(x, y)` coordinates
     (`delta <= 15px`), and newly entering characters must start off-stage or at
     `opacity: 0` rather than popping into the middle of the stage at frame `0`.
  3. **Authentic Carved Stagecraft Props Over Wireframe Lines (`镂空皮影砌末铁律`)**:
     On traditional shadow-puppet or cutout stages (`translucent: true`), never
     use raw geometric `code: path` lines for magical circles, halos, or binding
     rings — they read as crude vector wireframes. Always use carved translucent
     oxhide filigree cutout assets (`role: "prop"`, `cutout: true`, `blend: "multiply"`).
  4. **Ensemble Supporting Cast & Automated Gate**: Include active supporting
     characters in their own non-overlapping horizontal lanes to motivate plot
     turns, and run `python3 pipeline.py verify-continuity --timeline <timeline.json>`
     to verify scrolling transitions, backdrop/character handoffs, and prop fidelity.
  5. **Bidirectional Dramatic Facing & Local Forward-Rotation Sign Law (`flipX` & `rotate > 0`)**:
     Characters on a 2D stage must never all face a single static direction (e.g.
     facing right for the entire play while talking or kowtowing to someone on
     their left). Use `flipX: true` or keyframed `anim.flipX: [[f0, 0], [f1, 1, "step"]]`
     on the root character layer so the entire hierarchical rig mirrors around
     `pivotX` to face the partner during dialogue, slander, pleading, or kowtowing.
     **Local Rotation Sign Law**: Because both `renderers/quartz/compose.swift` and `remotion/Shot.tsx`
     apply `scaleBy(x: -scale, y: scale)` *before* `rotate(by: rot)`, a **positive
     `rotate` (`+35°..+45°`) ALWAYS pitches/bows the character FORWARD in the
     direction they are facing** (both when `flipX: 0` and when `flipX: 1`!), whereas
     a negative `rotate` (`-28°`) leans the character BACKWARD. Never use negative
     `rotate` for bowing or forward agony under `flipX: 1`!
  6. **Operatic Acting States, Bare-Hand Pose Swapping & Locomotion Separation (`行进态与表演态分离`)**:
     Never run full-shot alternating walking leg swings (`leg-front`/`leg-back`)
     or wide arm swings while a character is standing still to perform a dramatic
     action, and never wave a giant weapon overhead when a character is clutching
     their head or kowtowing:
     - **Incantation / Chanting (`念咒态`, e.g. Tang Monk chanting Tight-Fillet)**:
       Plant both feet completely still (`leg` rotation `0°`), plant the staff arm
       steady on the ground, hold the torso upright (`x` stationary), and animate
       only the prayer-bead hand (`arm-back`) in rapid, small-amplitude mudra
       tremors (`12°..28°` every `6..8` frames) with subtle head nods.
     - **Tight-Fillet Headache / Agony (`受创剧痛态`, `gait.mode: "shudder"`)**:
       Wait until the chanter actually begins chanting (never start clutching head
       during an earlier character's dialogue!), turn to face the chanter (`flipX: 1`),
       swap any weapon-bearing front arm via `poses` to a bare front arm
       (`*-arm-front`) so both hands clutch the temples without brandishing a weapon
       overhead, place the fillet halo prop directly on the brow (`y ~ 468`), drop
       deep onto the knees (`y >= +75px`, `leg-front: +55°`, `leg-back: -48°`), and
       pitch the torso violently forward and back (`rotate: +42° <-> -22° <-> +45°`)
       while `shudder` convulses both parent and child limbs.
     - **Three-Kowtow Farewell (`三叩首拜别态`)**:
       Turn toward the master (`flipX: 1`), swap the weapon arm via `poses` to a
       bare front arm (`*-arm-front`) with hands clasped (`-75°`), drop deep onto
       the knees (`y >= +75px`), and execute three distinct deep forward bows
       (`rotate: +6° -> +38° -> +8° -> +40° -> +8° -> +42°`) before restoring the
       weapon arm and leaping onto the cloud.
  7. **Piecewise Clause-Anchored Audio-Visual Sync (`分句声画锚点同步`)**:
     When authoring `captions` (`draw: "captions"`), place each subtitle item at
     the exact frame where its corresponding visual beat (strike, incantation,
     kowtow, prop reveal/hide, or scenery scroll) occurs. Running
     `python3 pipeline.py sync-audio --spec <spec>` matches those authored clauses
     against the synthesized TTS speech boundaries and piecewise-warps all layer
     keyframes (`anim`, `poses`, `gait.range`, `punches`) so every visual action
     stays 100% locked to the spoken narration.
  8. **Anatomical Carving Craft & Prop Lifecycle Discipline (`传统皮影造型与道具消散铁律`)**:
     - **Zero Geometric Face Patching**: Never synthesize character heads or faces
       (e.g., Zhu Bajie or Little Monkey) out of procedural circles/ellipses, and
       never leave a horizontal gap or another character's chin/beard below the
       neck. Always derive from authentic shadow-puppet master plates with
       seamless collar overlap and anatomical contour splitting (clean-shaven monk
       jawline for Tang Monk, zero beard/sideburns).
     - **Prop & Corpse Lifecycle (`stale_props` Gate)**: Every temporary spell
       prop (protective circle, fillet halo, bone cage, banishment scroll) and
       defeated corpse must fade out (`opacity -> 0`) as soon as its narrative
       beat concludes and strictly BEFORE any in-shot scenery scroll transition.
       Never reuse Act 1's protective ground circle at the end of the final act.

---

## Authoring Pitfalls (each one measured on a real render)

Every item below was found by running the pipeline, not by reading the code.
They are the failures that cost the most time.

1. **`z` must be unique per shot.** `validate` rejects duplicates with
   `duplicate z` — and z is the stacking order, so two layers sharing it have
   no defined order.
2. **A still-image shot fails the motion and freeze gates.** A plate with no
   camera move measures 0.000000 changed pixels and the freeze detector flags
   it. Pair every static plate with `motion: {"type":"geometric","zoom":[1.0,1.08]}`,
   `anim` keyframes, or an active `field`/`path`/`video` layer.
3. **Shot k must be GENERATED before shot k+1 runs S1.** A later shot's
   `first_frame`/`last_frame`/`input_asset` names an asset that does not exist
   yet, and S1 will say so. The order is: run shot k → (optionally
   `extract-frame`) → run shot k+1 → `concat`.
4. **A first-frame / reference source must be a STATIC one.** `grid` and `dots`
   are rendered to a PNG; `field`, `path`, `captions` and `bar` are drawn live
   by the renderer and have no file to hand to the model. A `code` layer with
   `draw: "field"` cannot be a `first_frame`.
5. **Keep the voiceover text long enough.** A 4-character line in a 5-second
   shot leaves the master near the gate's edge (-13.2 LUFS measured against a
   -16 target). 15+ characters lands solidly in [-16, -15].
6. **All shots in one timeline must agree on audio.** Every rendered mp4 now
   carries an audio stream — a silent shot gets a compliant silent track — so
   a mixed narrated/silent timeline is fine, but a shot whose file predates
   that change (or was made elsewhere) has no stream and `concat` refuses to
   assemble it.
7. **A `component` layer needs a project-side registry.** The engine ships
   none: put the component in `<project>/remotion-custom.tsx` exporting
   `CUSTOM_COMPONENTS`; `remotion.config.ts` aliases `project-custom` to it
   when `POSTER_ROOT` points at the project.
8. **Hailuo only does `first_frame`.** `last_frame` and `reference_images` are
   H3-family only, and `reference_type: "subject"` fails upstream AFTER
   billing on every model — `validate` refuses all three up front. See the
   capability table above.
9. **`flipX` mirrors around the CONTENT's center for a `text` layer** (so it
   does not jump across its `rect`), but the glyphs themselves are mirrored —
   which makes CJK text unreadable. Use `flipX` for figures and rigs, not for
   labels.
10. **A shot with text is not byte-reproducible.** See Core Invariant #1: the
    frames are identical in content, and a handful of pixels differ by
    antialiasing rounding.
11. **A `video` layer defaults to `fit: "cover"`, and cover CROPPS.** A 9:16
    clip in a 16:9 rect shows only the middle ~32% of its height; whatever
    moves outside that window never reaches the screen. The picture can then
    stand still for half a second while the source is moving — the motion
    gate passes (some pixels changed somewhere in the shot) and the freeze
    gate goes red. S4 says so in that case: *"the motion happened OUTSIDE the
    visible crop"*, with the clip size, the rect size, and how much was
    cropped away. Fix it by matching the clip's aspect to the rect, setting
    `"fit": "contain"` (the whole clip, letterboxed), or keeping the motion
    inside the window that is actually on screen.
