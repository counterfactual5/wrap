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
- Known engine boundaries for this mode: clips re-encode to the shot's fps
  and pixel format in S2 (no alpha survives — see pitfalls.md §15); loop seams of
  a single clip inside one shot are the model's cycle, visible if the motion
  is fast; plan shot lengths against the model's `max_dur`, not against hope.

Part of the wrap skill — see skills/wrap/SKILL.md; pitfalls referenced live in pitfalls.md.
