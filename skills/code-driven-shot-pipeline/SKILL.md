---
name: code-driven-shot-pipeline
description: >-
  Design, synthesize, and verify code-driven poster-style and short-video knowledge shots.
  Uses a 5-stage deterministic build system (Generate, Prepare, Compose, Gate, Inspect)
  with lockfile manifest invariants, aspect-ratio preservation, neural audio mastering,
  audio QC gates, visual self-audit contact sheets, and narrative timeline contracts.
---

# Code-Driven Shot Pipeline

## Overview

The **Code-Driven Shot Pipeline** treats motion graphics and video synthesis like software compilation. Rather than relying on non-deterministic AI video generation or manual timeline editing, it compiles a structured JSON specification (`spec/*.poster.json`) into 1080p (16:9 landscape or 9:16 vertical 1080x1920) 30fps broadcast-quality video clips through 5 decoupled stages, with built-in neural voiceover narration, broadcast mastering, audio quality gates, visual self-audit contact sheets, and multi-shot narrative timeline assembly.

## Core Invariants

1. **Manifest Authority (Lockfile Model)**:
   - Text-to-image AI APIs lack seed reproducibility.
   - Once generated, assets are frozen in `manifest.json` with their SHA256 checksums.
   - Subsequent pipeline runs strictly reuse frozen assets: `spec + manifest -> identical sha256 mp4`.
2. **Zero-Dependency Pixel & Audio Metrics**:
   - Avoid brittle FFmpeg `geq` filter expressions.
   - Extract raw video frames via `ffmpeg -f rawvideo` and measure pixel metrics in standard Python using bit-twiddling (`bytes.translate`, `int.from_bytes`, and `bit_count` popcounts).
   - Use resolution-independent metrics (`changed_pixel_ratio` instead of mean luma differences).
3. **Fail-Fast Keying Purity & Aspect-Ratio Preservation (S2)**:
   - AI subjects on white background use `blend=multiply` (or screen/normal for dark aesthetics).
   - The outer 8px perimeter must have $\ge 98\%$ key color purity. If edge gradients/vignettes exist, the build blocks at S2.
   - **Aspect-Ratio Preservation**: Full-canvas layers scale to fit zoom headroom; subregion card layers strictly preserve the source aspect ratio using `force_original_aspect_ratio=increase,crop={tw}:{th}` to prevent distortion (e.g. circles becoming ovals).
4. **Deterministic Audio-Visual Sync & Broadcast Mastering**:
   - Voiceover narration uses high-fidelity neural TTS (Microsoft Edge Neural TTS `zh-CN-YunxiNeural` with brisk `+18%` rate for viral pacing, fallback to local macOS speech).
   - Audio is mastered through a professional broadcast filter chain:
     - 75Hz highpass (eliminates mic rumble / plosives)
     - 250Hz low-mid EQ (+2.5dB warmth)
     - 3.2kHz presence EQ (+2.0dB speech clarity)
     - Dynamic compressor (`compand`) and `loudnorm=I=-16:TP=-1.5:LRA=11` targeting standard -16.0 LUFS.
   - Ambient soundscape is procedurally synthesized via 4-harmonic drone oscillation (55Hz sub, 110Hz bass, 220Hz mid, 440Hz shimmer with tremolo).
5. **Hero Motion Stage & Popular Science Narrative Invariant**:
   - Avoid cluttered academic text cards or raw intimidating math formulas.
   - The **Hero Physical Animation Stage** occupies 65%~70% of the viewport.
   - Replace abstract equations with **intuitive physical mental models** (e.g. Spacetime Trampoline, Gravity Funnel Rolling Marble, Eddington Eclipse Ray Bending, Spacetime Waves, Relativistic Accretion Photon Streams, Light Cone 90° Inversion).
   - Subtitles use a minimalist, translucent capsule (`cardType: "capsule"`) anchored below the stage.
6. **Multi-Shot Narrative Timeline Contract**:
   - Multi-shot timeline assemblies (`spec/timeline.json`) enforce structured editorial beats (`hook`, `development`, `climax`, `resolution`, `transition`) and explicit reasons.
   - Dialog/text alone is not completed state; only verified output artifacts under `build/` satisfy the completion contract.

## The 5 Stages

| Stage | Script / Command | Contract | Exit Codes |
|---|---|---|---|
| **S1 Generate** | `stages/01_generate.py` | Reads `spec` & `style.json`. Fetches AI assets into `assets/*.png` and records SHA256 in `manifest.json`. Reuses frozen assets. | `0` = Assets ready & verified<br>`1` = Generation/Network failure |
| **S2 Prepare** | `stages/02_prepare.py` | Measures outer 8px key purity on assets. Scales assets with aspect-ratio preservation and renders code background layers. | `0` = Purity $\ge 98\%$ & layers ready<br>`1` = Blocked by key impurity |
| **S3 Compose** | `stages/03_compose.py` (`remotion`) | Compiles spec with **Remotion** rendering engine (`remotion/index.tsx`). Synthesizes neural audio, applies -16 LUFS broadcast mastering, and produces lossless `build/frames/<shot-id>/%05d.png` and `build/<shot-id>.mp4` with BT.709 color metadata. | `0` = Frames, audio, and MP4 rendered |
| **S4 Gate** | `stages/04_gate.py` | Analyzes lossless PNG frames for motion delta, color accent presence, freeze frames (`freezedetect`), and evaluates audio QC (silence, -16 LUFS loudness, and AV duration sync $\le 100$ms). | `0` = All gates pass<br>`1` = Metric out of bounds |
| **S5 Inspect** | `stages/05_inspect.py` | Extracts an 8~12 frame tiled contact sheet (`build/contact_sheet_{shot_id}.png`) and generates a spec layer checklist (`build/inspection_{shot_id}.json`) for visual self-audit against hallucination, misorientation, or text overlap. | `0` = Contact sheet & checklist ready |

## Supported Layer Types

Specifications (`spec/*.poster.json`) support 5 declarative layer types:
1. **`ai`**: Image assets with geometric zoom/pan, blend mode (`multiply`, `screen`, `normal`), and key color.
2. **`code`**: Procedural shapes and physics SVG simulations:
   - `grid`, `dots`, `bar`: Structural backgrounds and panning accents.
   - `trampoline`: 3D perspective spacetime mesh sinking under gravitational mass.
   - `gravity-well`: Deep gravitational funnel with orbiting planet (marble trajectory).
   - `light-deflection`: Ray tracer showing gravitational light bending + apparent ghost position shift.
   - `spacetime-waves`: Binary compact masses radiating expanding quadrupole gravitational wave ripples.
   - `blackhole-hero`: Relativistic accretion disk with Doppler-boosted photon ring and ISCO orbits.
   - `time-dilation`: Dual observer perspective clocks with asymptotic freeze and gravitational redshift.
   - `light-cone-tilt`: Minkowski light cone tilting 90° inside event horizon towards singularity.
   - `spaghettification`: Tidal tensor stretching falling body into an atomic filament.
3. **`text`**: Headings and titles with physical spring entrance animation and gradient glow.
4. **`hud`**: Scientific HUD elements (`badge`, `telemetry`, `equalizer`, `progress`, `scanline`).
5. **`card`**: Knowledge cards:
   - `capsule`: Minimalist floating subtitle capsule for high-retention short videos.
   - `formula`: Scientific formula breakdown with interactive parameter tags.
   - `quote`: Highlighted quote with author attribution.

## Audio Specification & QC Gates

Add voiceover narration and BGM directly to any shot:
```json
"audio": {
  "voiceover": "你有没有想过，地球绕着太阳转，并不是因为太阳拉住了地球...",
  "voice": "zh-CN-YunxiNeural",
  "bgm": "ambient"
}
```

### Audio QC Gates (in S4):
- **`audio_silence`**: Verified via `volumedetect`. Max volume must be $> -45.0\text{ dB}$ (prevents silent / empty audio tracks).
- **`audio_loudness`**: Measured via EBU R128 filter. Integrated loudness must fall within target $\pm 2.5\text{ LUFS}$ (`[-19.0, -13.0]` LUFS, targeting standard `-16.0 LUFS`).
- **`audio_av_sync`**: Stream duration alignment. $\left|\text{duration}_{\text{video}} - \text{duration}_{\text{audio}}\right| \le 0.100\text{s}$ ($100\text{ms}$).

## Visual Self-Audit (S5: `stages/05_inspect.py`)

Solves the blind spot of pure statistical pixel gates:
- Extracts 9 or 12 evenly-spaced frames into a 3x3 or 4x3 contact sheet (`build/contact_sheet_{shot_id}.png`).
- Generates a spec-derived checklist (`build/inspection_{shot_id}.json`) covering:
  - Text legibility: No overlapping characters, clean hierarchy, no raw HTML/JSX tags.
  - Subject fidelity: Visual subject matches declared AI asset / code draw type without aspect-ratio stretching.
  - Motion coherence: Physical animation progresses logically across the frames.
- Registers visual audit completion into `build/gates/<shot-id>.json`.

## Narrative Timeline Format & Contract

Multi-shot sequences are defined in `spec/timeline.json` with explicit narrative roles:
```json
{
  "id": "blackhole-journey-1min",
  "shots": [
    {
      "spec": "spec/blackhole-shot-01.poster.json",
      "beat": "hook",
      "reason": "以震撼的相对论吸积盘与光子球奇观抓住观众注意力，建立黑洞物理的宏大空间尺度"
    },
    {
      "spec": "spec/blackhole-shot-02.poster.json",
      "beat": "development",
      "reason": "提出引力时间膨胀反常识现象：双参考系对比揭示远方同伴眼中探测器无限冻结与红移"
    },
    {
      "spec": "spec/blackhole-shot-03.poster.json",
      "beat": "climax",
      "reason": "时空几何核心反转：视界内光锥倾倒90度，径向空间变为不可逃避的时间未来"
    },
    {
      "spec": "spec/blackhole-shot-04.poster.json",
      "beat": "resolution",
      "reason": "潮汐力面条化与已知物理在奇点的崩溃，以哲学警句收束全篇"
    }
  ]
}
```

Supported beats: `hook`, `development`, `climax`, `resolution`, `transition`, `intro`, `outro`.

## Quick Start & CLI Usage

### 1. Initialize a new shot
```bash
python3 pipeline.py init-shot shot-02
```

### 2. Run full 5-stage pipeline on single shot
```bash
python3 pipeline.py run --spec spec/blackhole-shot-01.poster.json
```

### 3. Generate visual self-audit contact sheet (S5)
```bash
python3 pipeline.py inspect --spec spec/blackhole-shot-01.poster.json --grid 3x3
```

### 4. Concatenate narrative multi-shot sequence into 1-minute video
```bash
python3 pipeline.py concat --timeline spec/blackhole-timeline.json --output build/blackhole_full_1min.mp4
```

### 5. Run automated test suite
```bash
python3 pipeline.py test
```
