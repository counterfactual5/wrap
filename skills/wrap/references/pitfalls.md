# Authoring pitfalls (measured on real renders)

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
11. **Freeze detection is not an exact duplicate-frame test.** ffmpeg's
    `freezedetect` compares the whole frame against a reference and counts it
    as unchanged when the mean absolute difference is below 0.1% of full scale
    (`n=0.001`). So sparse, periodic, or low-contrast motion may be flagged
    even while the shot visibly moves, and a slow but nonzero drift may read
    unchanged if too few pixels move far enough. For slow/varied compositions
    prefer a single wide/full-field drift (or declare `frame_freeze` with
    documented intent) rather than many micro-movements on near-nothing.
    Inspect actual frames before changing anything; do not prescribe particle
    counts or motion amplitudes for all projects.
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


Part of the wrap skill — see skills/wrap/SKILL.md.

17. **Gate PASS is not visual plausibility.** A shot can satisfy every
    motion, purity, silence and freeze gate while the authored figure/object
    reads as an unrelated blob, stick figure or scattered collection of
    rectangles — the gate cannot see whether the silhouette coheres. Always
    inspect the rendered output once with fresh eyes and ask: "does this look
    like [the thing it claims to be]?" This single check will catch the
    failure before release.

Part of the wrap skill — see skills/wrap/SKILL.md.
