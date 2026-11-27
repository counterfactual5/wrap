# The seam-chained i2v path (one production mode among several)

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
- **Keyframe identity is not free — verify it, do not assume it.** When a
  clip is generated from a `first_frame` AND a `last_frame`, the generator
  interpolates between two *pictures*. If the two pictures are not the same
  garment/vehicle/face, the clip morphs from one into the other, and the
  morph plays out in full inside the shot. Measured: a shirt that had to be
  "the same one" came back short-sleeved, clean and bright blue with
  orange buttons — a ~55-unit chroma swing, exposed for 3.5 s, read by the
  audience as a glitch. Before spending the clip call:
  1. generate the second reference still **with the first one as the
     reference image**, and
  2. verify identity on **form**, not just colour: sleeve length, button
     colour, stains/wear, pocket shape, weave — plus a chroma number
     (R−B) on the subject region of both stills. Colour alone is not
     identity: two different garments of the same hue pass a colour check
     and still morph.
  A colour check alone is how "the root cause is fixed" was declared on a
  morph that was still there.
- **Known engine boundaries for this mode**: clips re-encode to the shot's fps
  and pixel format in S2 (no alpha survives — see pitfalls.md §15); loop seams of
  a single clip inside one shot are the model's cycle, visible if the motion
  is fast; plan shot lengths against the model's `max_dur`, not against hope.
- **A clip's audio track is often shorter than its picture.** The engine
  time-stretches the audio to fill the shot, so a fade-out that lives near
  the end of the source lands at ~90% of the shot's length — always at the
  wrong moment. Trim the shot to the audio's plateau, and check the seam's
  audio envelope (a dip that RECOVERS is a hole; a dip that stays down is a
  fade). The whole-film gate now fails a cut whose audio drops and comes back.

## The four checks a seam must pass before it ships

Measured seams fail in these four ways; each has a check that catches it.

| # | What breaks | How it is caught |
|---|---|---|
| 1 | The two keyframe stills are not the same subject, so the clip morphs | Compare the subject's R−B **and** its form (sleeves, buttons, wear, pocket, weave) across the two stills, and the chroma sweep across the clip's frames |
| 2 | The picture jumps scale at the cut (near → wide) and nothing explains it | Measure the mean |Δluma| across the cut against the shot's own frame-to-frame variation; if it stands out, the cut is a visible jump — either match the framings or name the reset in the copy |
| 3 | The audio dips under the cut and recovers (a hole, not a fade) | `gates_full_*.json` → `seam_audio_hole` (the level before, under and after the cut). It reads the level in **20 ms windows**: a long window averages a short hole away, and a gate that reports "clean" over a real dip is worse than no gate |
| 4 | A short black dip at the cut is invisible to the old gate | `gates_full_*.json` → `black` and `black_with_sound` |

## The delivered film must BE the encoding of the frame master

A shot ships as two artifacts: the frame master (`build/frames/<shot>/*.png`) and the
delivered mp4. Nothing in the pipeline used to compare their **pixels** — the manifest
binds the frames to the shot, and that is all. So an encoder that loses frames produces a
video that no longer matches the master it was encoded from, and every quality gate passes
it.

Measured: Remotion writes RGBA only for the frames that carry transparency and RGB for the
rest, so a rendered sequence mixes color types; the PNG demuxer then changes the decoded
format mid-stream, ffmpeg reconfigures the filter graph, the overlay's frame sync resets,
and the encoder emits the bare background sheet — a black frame — at positions that **differ
from run to run** (five encodes of the same 360 frames lost five different sets of frames).

Checks:

- S3 normalizes the sequence to one pixel format before encoding; the pixels do not change.
- S4's `master_match` gate composites the master over the canvas background the way the
  encoder does and differences the two streams; a correct render stays at or below ~1.5
  mean |ΔY| (the encoder's own quantization), a corrupted one at 35–61.
- **When reviewing a delivered film, check the binding yourself**: decode the mp4 and the
  master, find the flat/black frames in each, and compare the sets. They must be identical.
  A black frame in the film that is not a transparent frame in the master is a lost frame.
  Do not conclude "the video is from a different render" — re-encode the master with the
  engine's own command and compare; if the re-encode loses frames too, the encoder is the
  problem, not the render.

## The renderer can leave a frame empty — and that frame reaches the film as a black hole

Remotion paints a video layer from a `<video>` element. That element can fail to deliver the
frame it was asked for: it stays empty, the layer leaves a transparent gap, and the encoder
composites the gap over the canvas background. The delivered film then has a **black hole**
in it, with the soundtrack still playing underneath — a viewer sees the picture blink out.

Measured on a real H3 clip (180 frames, one video layer covering the canvas): the first
render left gaps at frames 89 and 90, and **the same spec re-rendered produced none**. The
defect is a race in the renderer, not a property of the spec, so re-running the pipeline is
not a fix — only a guard is.

Checks:

- S3 now runs the hole guard: it reads the rendered frame sequence, measures each frame's
  mean alpha, and compares it with what the spec promised there (the strongest lower bound
  the spec's video layers give — opacity × rect area). A frame that falls more than 5 %
  below its promise is a hole.
- The shot is re-rendered while holes remain (the race is not reproducible, so a second
  render usually comes back clean). A shot that still has holes after the last attempt
  **fails in S3 and is never encoded** — the bar is never lowered to let a hole through.
- `core/rendering/holes.py` is the guard; `core/rendering/compose.py` is the flow. A frame
  the spec fades out on purpose is not a hole: the promise falls with the opacity.
- **"mean alpha = 1.0" is not evidence of "no transparent frame".** If the master PNGs carry
  no alpha channel at all (colour type 2, RGB), every frame reads 1.0 by construction and the
  measurement cannot fail. What proves the absence of holes in that case is the **absence of
  the alpha channel itself** — plus the frame count, the black-frame check and the freeze
  check. Quoting the measured alpha as if it were a test is a vacuous check, and an
  independent reviewer will say so.
- **When reviewing a delivered film, look for the holes yourself**: the `black` and
  `black_with_sound` rows in `gates_full_*.json` report them, but they only run on the
  assembled film. Decode the frame master and look for transparent regions where a video
  layer should have painted — a transparent frame in the master is a hole, and it became a
  black frame in the film.

Part of the wrap skill — see skills/wrap/SKILL.md; pitfalls referenced live in pitfalls.md.