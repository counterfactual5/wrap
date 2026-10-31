---
name: code-driven-shot-pipeline
description: >-
  Design, synthesize, and verify code-driven poster-style video shots.
  Uses a 4-stage deterministic build system (Generate, Prepare, Compose, Gate)
  with lockfile manifest invariants and stdlib pixel metric gates.
---

# Code-Driven Shot Pipeline

## Overview

The **Code-Driven Shot Pipeline** treats motion graphics and video synthesis like software compilation. Rather than relying on non-deterministic full-video generation or manual video editing, it compiles a structured JSON specification (`spec/*.poster.json`) into 1080p 30fps video clips through 4 decoupled stages.

## Core Invariants

1. **Manifest Authority (Lockfile Model)**:
   - Text-to-image AI APIs lack seed reproducibility.
   - Once generated, assets are frozen in `manifest.json` with their SHA256 checksums.
   - Subsequent pipeline runs strictly reuse frozen assets: `spec + manifest -> identical sha256 mp4`.
2. **Zero-Dependency Pixel Metrics**:
   - Avoid brittle FFmpeg `geq` filter expressions.
   - Extract raw video frames via `ffmpeg -f rawvideo` and measure pixel metrics in standard Python using bit-twiddling (`bytes.translate`, `int.from_bytes`, and `bit_count` popcounts).
   - Use resolution-independent metrics ("changed pixel ratio" instead of mean luma differences).
3. **Fail-Fast Keying Purity (S2)**:
   - AI subjects on white background use `blend=multiply` (or screen for black).
   - The outer 8px perimeter must have $\ge 98\%$ key color purity. If edge gradients/vignettes exist, the build blocks at S2 before spending time composing.

## The 4 Stages

| Stage | Script / Command | Contract | Exit Codes |
|---|---|---|---|
| **S1 Generate** | `01_generate.py` | Reads `spec` & `style.json`. Fetches AI assets into `assets/*.png` and records SHA256 in `manifest.json`. Reuses frozen assets. | `0` = Assets ready & verified<br>`1` = Generation/Network failure |
| **S2 Prepare** | `02_prepare.py` | Measures outer 8px key purity on assets. Scales assets with zoom headroom and renders code background layers. | `0` = Purity $\ge 98\%$ & layers ready<br>`1` = Blocked by key impurity |
| **S3 Compose** | `03_compose.py` (`remotion`) | Compiles spec with **Remotion** rendering engine (`remotion/index.tsx`). Produces lossless `build/frames/%05d.png` and `build/<shot-id>.mp4` with BT.709 color metadata. | `0` = Frames and MP4 rendered |
| **S4 Gate** | `04_gate.py` | Analyzes lossless PNG frames for motion delta, color accent presence, and freeze frames (`freezedetect`). | `0` = All gates pass<br>`1` = Metric out of bounds |

## Quality Gate Metrics

- **`changed_pixel_ratio`** (`motion`):
  Fraction of total pixels between adjacent frames whose Luma difference $> 6$. Resolution-independent. Typical target range: `[0.0005, 0.08]`.
- **`subject_motion_ratio`** (`subject`):
  Fraction of pixels with Luma difference $> 6$ outside excluded foreground bands (e.g. animated bar), preventing bar motion from masking a static subject. Typical target range: `[0.0005, 0.08]`.
- **`red_pixel_ratio`** (`red`):
  Fraction of pixels matching RGB accent mask ($R > 120, G < 90, B < 90$). Typical target range: `[0.002, 0.02]`.
- **`accent_color_ratio`** (`accent`):
  Fraction of pixels matching arbitrary hex accent color mask from spec layer. Typical target range: `[0.002, 0.02]`.
- **`edge_key_purity`** (`keyPurity`):
  Fraction of outer 8px boundary pixels matching the key color (e.g. `#ffffff`) within tolerance ($\le 12$). Threshold: $\ge 0.98$.
- **`freezedetect`** (`freeze`):
  Number of unintended freeze segments $> 0.5\text{s}$. Must be `0`.

## Prerequisites
- `ffmpeg` (version >= 5.0 with `x264`, `freezedetect`)
- `python3` (version >= 3.10)
- `node` (version >= 18.0) and `npm` (run `npm install` for Remotion dependencies)

## Quick Start & CLI Usage

### 1. Initialize a new shot
```bash
python3 pipeline.py init-shot shot-02
```

### 2. Run full pipeline
```bash
python3 pipeline.py run --spec spec/shot-02.poster.json
# or via Makefile
make run
```

### 3. Run individual stages
```bash
python3 pipeline.py validate --spec spec/shot-02.poster.json
python3 pipeline.py generate --spec spec/shot-02.poster.json [--force]
python3 pipeline.py prepare  --spec spec/shot-02.poster.json
python3 pipeline.py compose  --spec spec/shot-02.poster.json
python3 pipeline.py gate     --spec spec/shot-02.poster.json
```

### 4. Run automated test suite
```bash
make verify
# or
python3 pipeline.py test
```

## Common Mistakes & Anti-Patterns

1. **Treating pan/zoom motions as prose instead of numeric endpoints**:
   - Bad: `"motion": "slow push in"`
   - Good: `"motion": { "type": "geometric", "zoom": [1.0, 1.06] }`
2. **Confusing pan endpoints with relative offsets**:
   - `pan: [0, 540]` defines $X$ moving from $0$ to $540$. Treating it as $[dx, dy]$ causes the layer to drift off canvas in $Y$.
3. **Measuring metrics on lossy MP4 instead of lossless PNG frames**:
   - H.264 compression artifacts and chroma subsampling (yuv420p) distort delicate pixel ratio counts. Always measure S4 gates against `build/frames/%05d.png`.
4. **Using FFmpeg `geq` filter**:
   - `geq` filter expressions have escaped comma syntax and platform inconsistencies. Always pipe raw video bytes into Python stdlib.
