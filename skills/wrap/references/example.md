# A minimal shot, end to end — built and gated, not sketched

One sample of the *shape* of the pipeline: spec → component → render → gate →
judge. **Copy the shape, not the look.** This example is one possible aesthetic
decision on a Tuesday; your subject re-derives its own. It is an illustration,
not a starting point for a new video's design, and it demonstrates no generated
assets (it also runs with zero generation backends, which is the point).

Verified end to end on this repo (macOS, Node 25, `python3.12`) during skill
authoring: all gates passed, judge verdict `pass`.

## Layout

```
wrap-example/                 # POSTER_ROOT — NOTE: path must contain NO dot anywhere, not just in the final segment
  remotion-custom.tsx         # the component registry (project-owned)
  spec/minimal-01.poster.json
```

> Remotion's image-sequence CLI splits the whole output path on `.` and
> rejects it (`Cannot have an extension`) — any dot in any parent segment
> (e.g. `my.proj/`, or a `.tmp` ancestor) breaks the render. The engine now
> preflights this and fails before npm runs, naming the offending segment;
> keep the project path dot-free.

## File 1 — `remotion-custom.tsx`

```tsx
import React from 'react';
import type {CustomComponentRegistry} from 'remotion/registry/types';

const INK = '#10131A';
const STRIP = '#1E2536';
const PAPER = '#F4F1EA';
const VERMILION = '#E4523B';

export const CUSTOM_COMPONENTS: CustomComponentRegistry = {
  TitleCard: ({frame, fps, props}: any) => {
    const enter = Math.min(1, frame / 24);
    const ease = 1 - Math.pow(1 - enter, 3);
    const underline = Math.max(0, Math.min(1, (frame - 15) / 30));
    const drift = (frame * 1.6) % 2400;
    return (
      <div style={{position: 'absolute', inset: 0, background: INK, overflow: 'hidden',
                   fontFamily: 'Helvetica, Arial, "PingFang SC", sans-serif'}}>
        <div style={{position: 'absolute', top: 0, bottom: 0, width: 220,
                     left: drift - 110, background: STRIP}} />
        <div style={{position: 'absolute', top: 0, bottom: 0, width: 90,
                     left: drift + 420 - 45, background: STRIP}} />
        <div style={{position: 'absolute', left: 120, top: 360,
                     color: VERMILION, fontSize: 26, fontWeight: 700,
                     letterSpacing: `${6 + ease * 8}px`, opacity: ease}}>
          {props.kicker}
        </div>
        <div style={{position: 'absolute', left: 120, top: 410, width: 1500,
                     color: PAPER, fontSize: 92, lineHeight: 1.18, fontWeight: 800,
                     opacity: ease, transform: `translateY(${(1 - ease) * 34}px)`}}>
          {props.headline}
        </div>
        <div style={{position: 'absolute', left: 120, top: 730, height: 6,
                     width: `${underline * 460}px`, background: VERMILION}} />
      </div>
    );
  },
};
```

What to notice: the component positions itself in canvas coordinates (no wrapper
offset is applied); `frame`/`fps` arrive as props and motion is plain math — no
library idioms; `props` is the opaque bag from the spec; the entrance is
front-loaded so something is clearly happening in the first ~1.5 s; two
background strips drift **for the whole duration** so the median-changed-pixels
motion gate holds (see the gotcha below).

## File 2 — `spec/minimal-01.poster.json`

```json
{
  "id": "minimal-01",
  "canvas": {"w": 1920, "h": 1080},
  "fps": 30,
  "durationInFrames": 150,
  "layers": [
    {"id": "title", "type": "component", "component": "TitleCard",
     "rect": [0, 0, 1920, 1080], "z": 0,
     "props": {"kicker": "A MINIMAL SHOT", "headline": "Every video starts as a spec."}}
  ],
  "gates": [
    {"id": "motion", "metric": "changed_pixel_ratio", "lo": 0.0005, "hi": 0.6, "lumaDelta": 6}
  ],
  "tracks": {"captions": [], "events": []},
  "checklist": [
    "The kicker and headline read clearly at delivery size",
    "The card visibly changes during the first second and the background strips drift for the rest of the shot",
    "Nothing on screen fails the 3-meter read test"
  ]
}
```

## Run it

```bash
POSTER_ROOT=/path/to/wrap-example python3 pipeline.py run --spec spec/minimal-01.poster.json
```

Actual output (abbreviated):

```
PASS  motion     changed_pixel_ratio  0.003054  [0.0005, 0.6]
PASS  freeze     freezedetect         0 frozen segment(s)
PASS  silence    silent shot peak     -91.0 dB  [< -45.0 dB]
PASS  av_sync    duration_delta       0.008 s  [<= 0.100 s]
PASS  encoder   ffmpeg_fingerprint   manifest=921ec1526658 live=921ec1526658
[S5 judge] ... contact sheet is PENDING judge
```

The verdict is deliberately **not** self-blessing: read `build/contact_sheet_minimal-01.png`, then

```bash
python3 pipeline.py judge --spec spec/minimal-01.poster.json --verdict pass --notes "Kicker/headline enter with ease-out; underline sweep completes by frame 45; background strips drift continuously; silent by design."
```

## Gotchas this example paid to learn

1. **The motion gate is a *median* over adjacent-frame pairs.** An entrance
   animation that plays only for the first 40 of 150 frames leaves the median
   near zero and the gate fails. Either keep something else drifting for the
   whole shot (as above), or own the stillness with `frame_freeze: true` and
   documented intent — never nudge the gate to hide a dead frame.
2. **lumaDelta is a per-pixel brightness delta, not a color-difference delta.**
   A drift strip only 5 luma points from its background is invisible to the
   gate; `#1E2536` on `#10131A` (~18) is safely above 6.
3. **Silent by design requires no `audio` key at all.** Adding an empty one
   still parses, but absence is the documented default.
4. **Charset/fonts come from the render host, not the engine.** Chromium used
   this machine's system fonts (Helvetica/PingFang SC); a headless Linux box
   without CJK fonts would render boxes — the spec cannot fix that, the host
   must have the fonts.
5. **`.poster.json` checklist is read by the judge prompt.** Keep items
   concrete and falsifiable ("reads clearly at delivery size"), not vibes.

## What to copy vs what to author fresh

Copy the *shape*: one component with a small `props` bag, plain frame math,
continuous motion under the median gate, self-reported checklist, judge pass
recorded with evidence. Author fresh everything else — palette, typeface,
layout, motion language — those are the subject's, not this file's.

For an audio-first, generated-asset or multi-shot version of this exercise, see
`references/seam-chained-i2v.md` and the stage table in `SKILL.md`; this example
is the zero-asset, zero-backend floor.

Part of the wrap skill — see `skills/wrap/SKILL.md`.
