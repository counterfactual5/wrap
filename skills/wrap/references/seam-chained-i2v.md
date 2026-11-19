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
| 3 | The audio dips under the cut and recovers (a hole, not a fade) | `gates_full_*.json` → `seam_audio_hole` (the level before, under and after the cut) |
| 4 | A short black dip at the cut is invisible to the old gate | `gates_full_*.json` → `black` and `black_with_sound` |

Part of the wrap skill — see skills/wrap/SKILL.md; pitfalls referenced live in pitfalls.md.
