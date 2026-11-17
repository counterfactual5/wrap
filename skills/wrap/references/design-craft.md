# Design craft for video — principles, not prescriptions

What this file is: a checklist of *questions and tradeoffs* for authoring the
visual layer — the spec layers, the `remotion-custom.tsx` components, the
review that catches "green gates, dead film". What this file is **not**: a
template, a palette, a component library, a scene recipe. If any line here
starts to feel like "always do X", apply the counterexample instead — flat
monochrome, typographic-only and deliberately static are all valid films in
this engine; decorative additions are never required to pass review.

The engine ships none of this. You (the authoring model) carry it per video.

## The one anchor question

Before any layer exists, answer in one sentence:

> **In this shot, what should the viewer look at, and when?**

If you can't name it, the shot has no design yet — no matter how many gates
might pass. Every hierarchy decision below hangs off that answer.

## Type in motion

- **Two levels of type max per frame**: one voice for the thing, one for the
  support. A third level says the layout is hedging.
- **Reading time is set by physics, not taste**: Chinese ≈ 4–5 chars/sec/
  comfortable line, English ≈ 12–17 chars/sec. If text must be read, hold it
  long enough *plus* the transition time. If it can't be held that long, cut
  the text — don't shrink the font.
- **Caps for labels, not for sentences.** CJK has no caps; use weight/size/color
  as the case system.
- **Never raw text on an imagery background.** Add a scrim, a solid block, or
  a stroke — then test at frame, not at intention. Generated skies defeat
  light gray text; deep navy skies defeat near-black text.
- **Break lines by meaning, not width.** A clause split across a line break
  reads aloud wrong.
- **Legibility floor**: if any viewer path through the shot can't parse the
  glyphs in one glance at delivery size, the shot failed — regardless of
  aesthetic coherence.

## Color — the small rules that matter more than taste

- **One accent per shot.** A second accent is a different film's grammar.
- **Contrast lives in the large areas**, not the details: background vs figure
  is where readability and mood are set. Fine hairline details in the same
  value as the field will not survive antialiasing + compression.
- **Body text contrast ≥ 4.5:1** against its *immediate* backdrop
  (WCAG AA as a floor); display type on imagery needs no less.
- **Equally-distributed mediocre gray reads as unfinished.** Either commit to
  near-black/near-white or to a saturated field with intent — not mush.
- **Count colors before you ship.** More than ~4 flat colors in one frame
  usually means no decisions were made; either justify or remove.
- **The flat, high-key, low-chroma look is equally valid** — it is a choice,
  not a failure to reach the moody one.

## Motion — legibility before flair

- **Change on the beat**: place motion accents (entrances, swaps, reveals) on
  cut/beat boundaries of the script, not uniformly across frames. Motion
  between beats should be settle, not event.
- **Time constant discipline**: entrance/one-shot transitions ≈ 12–24 frames
  (0.4–0.8 s at 30 fps); continuous drift/pan 3–10 px per frame; anything
  faster reads as a glitch, anything slower reads as frozen (see
  `pitfalls.md` §14).
- **Ease everything except the linear travel** (scrolls, drifts). Cuts and
  snaps benefit from `snap`/`overshoot`; fades are `inout`.
- **Element motion > global motion** for aliveness: a subject element moving
  reads alive; a global zoom over a dead composition still reads dead.
- **One variable per gesture.** Scale + rotate + fade + slide in the same
  20 frames is mush; pick the variable that expresses the idea.
- **Dead tail is a decision too.** If the shot ends still, that stillness must
  be composed (holds a pose, holds a line) — not residual.

## Composition on a canvas

- **Safe areas**: keep text and faces inside ~85% of the frame height and
  ~88% of width for 16:9; for 9:16 vertical, the bottom 12% is caption
  territory — don't fight it, use it or avoid it.
- **One focal point per frame**; if two elements compete, one loses via size,
  contrast, or focus — decide which before first render, not after.
- **Thirds/center symmetries are tools, not prayers**: center for ceremony and
  stillness; off-center for direction and energy.
- **Scale = meaning**: the subject's screen size signals its narrative weight.
  A tiny hero in a huge frame is a lonely film; create it on purpose.
- **Read direction**: left-to-right (en) settles motion rightwards → rightward
  reveals feel productive, leftward reveals feel like return/retreat; CJK
  vertical/horizontal semantics invert some of this — follow the text, not
  the rule.
- **Negative space is a composition element**, not unfinished layout: a frame
  with breathing room focuses harder than one with props everywhere.

## Time — rhythm is a variable

- **Average shot length guides edit intent**: 2–4 s per shot is immersive
  intimacy; 5–8 s is contemplation; ≥10 s demands a reason (a single unfolding
  statement). Long shots are a promise, not a default.
- **Let the cut breathe**: after a read-aloud line lands, hold 0.5–1.5 s
  before the next event — comprehension happens in the hold.
- **Silence is a track too.** A beat of no audio can carry more than a sting;
  decide where the film hushes on purpose.
- **Don't stack events within one breath** (motion + cut + line + SFX in the
  same 12 frames): split into two beats.

## Working with generated assets

- **Prompt for emptiness, not abundance**: isolated subject, clean unified
  background, no text artifacts — easier to cut out, easier to light, easier
  to layer. ("no text", "no watermark", "single subject on white".)
- **Verify before freezing**: check the render at S2 (key purity ≥ 0.98) and,
  more importantly, *look at it*; models hide sins in thumbnails.
- **Faces and hands**: only if the backend is known-safe for them at your
  resolution; otherwise crop to silhouette/texture/hands-off framing.
- **Ask for cutouts in the pair phase, not the poster phase**: a frozen
  RGBA still composes layers better than any keyColor-removal after the fact
  (see `pitfalls.md` §16).

## Failure smells (quick sniff test)

- All green gates, zero reaction on first watch → pitfall §14; the film needs
  real events, not more drift.
- Every frame pulses at the same cadence → the film has a tempo but no rhythm.
- Text nobody can read in 1 s at arm's length → type role mismatch.
- Everything is centered and symmetric → the film has no opinion about where
  things go.
- Five+ hues, three+ type scale steps, zero hierarchy decisions → the shot was
  assembled, not designed.
- "Could we just add particles/zoom/grain?" → checklist dressing; see the
  pitfall about dodging freeze detection.

## When to ask for a second pair of eyes

If the shot involves an unusual camera, POV, typography experiment, or a short
deadline with no prior art, that's the signal for the rendered-review role
(see `orchestration.md`) — a fresh judge reading the contact sheet
finds what the author cannot, not because they're smarter but because they're
not you.

## Where this list gets extended

This file is the floor, not the ceiling. If your environment has a
**frontend-design** skill available, you may load it for the typography,
legibility and anti-templated-default passes — but take only the disciplines
(type craft, legibility checks, aesthetic direction); ignore its web layout,
responsive and interactivity parts — those are UI, not film. The counterweight
to all of this is always the audience and the subject: this film's value might
be precision, craft, motion or stillness — let that name the checklist, not
vice versa.

Part of the wrap skill — see `skills/wrap/SKILL.md`; pitfalls referenced live
in `pitfalls.md`.
