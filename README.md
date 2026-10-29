# Poster Video Pipeline (Code-Driven Single-Shot)

A deterministic, code-driven video synthesis pipeline that compiles a structured shot specification (`spec/*.poster.json`) into 1080p 30fps video using 3 layers:
1. **Code Background** (Procedural grid)
2. **AI Subject** (City silhouette, blend: multiply, edge keying)
3. **Code Foreground** (Animated geometric accent bar)

---

## Architecture & Stages

```
spec/*.json ───► [ S1: Generate ] ───► assets/*.png ───► (manifest lockfile)
                         │
                         ▼
                 [ S2: Prepare  ] ───► build/prepared/*.png (Fail-fast: key purity >= 0.98)
                         │
                         ▼
                 [ S3: Compose  ] ───► build/frames/*.png + build/*.mp4 (Single FFmpeg filtergraph)
                         │
                         ▼
                 [ S4: Gate     ] ───► build/gates.json (Zero-dependency rawvideo pixel metrics)
```

| Stage | Command / Script | Inputs | Outputs | Exit Code Contract |
|---|---|---|---|---|
| **S1** | `01_generate.py` | `spec/`, `manifest.json` | `assets/*.png`, `manifest.json` | `0` = Assets ready & verified; `1` = Error |
| **S2** | `02_prepare.py` | `assets/`, `spec/` | `build/prepared/*.png` | `0` = Scaled & pure; `1` = Blocked by key purity `< 0.98` |
| **S3** | `03_compose.py` (`.sh`) | `build/prepared/`, `spec/` | `build/frames/%05d.png`, `build/*.mp4` | `0` = 150 frames & MP4 encoded |
| **S4** | `04_gate.py` | `build/frames/`, `build/*.mp4` | `build/gates.json` | `0` = All gates pass; `1` = Quality violation |

---

## Core Invariants

1. **Manifest Authority (Lockfile Pattern)**:
   AI asset generation is non-reentrant (no seed parameter). Once generated, assets are recorded in `manifest.json` with their `sha256` checksum. Subsequent runs strictly reuse verified assets, ensuring bit-for-bit reproducibility of the final MP4 (`spec + manifest -> identical sha256`).
2. **Zero-Dependency Pixel Metrics**:
   Bypasses unstable FFmpeg `geq` filter expressions. Uses `ffmpeg -f rawvideo -> Python stdlib` with bit-twiddling (`bytes.translate`, `int.from_bytes`, and `bit_count` popcounts) for lightning-fast and resolution-independent pixel analysis.
3. **Fail-Fast Keying Purity**:
   Outer 8px perimeter is measured before composition. Impure backgrounds are rejected at S2 before spending compute on composition.

---

## Quality Gates

| Gate | Metric | Definition | Threshold |
|---|---|---|---|
| `motion` | `changed_pixel_ratio` | Median fraction of pixels with Luma $\Delta > 6$ | `[0.0005, 0.08]` |
| `red` | `red_pixel_ratio` | Median fraction of red accent mask pixels | `[0.002, 0.02]` |
| `keyPurity` | `edge_key_purity` | Fraction of outer 8px border matching key color within tolerance | `≥ 0.98` |
| `freeze` | `freezedetect` | Unintended frozen segments | `0` segments |

---

## Quick Start

### 1. Prerequisites
- `ffmpeg` (version >= 5.0 recommended, with `x264`, `zoompan`, `blend`, `overlay`, `freezedetect`)
- `python3` (version >= 3.10, standard library only)

### 2. Verify and Test
```bash
make verify
# or
python3 pipeline.py test
```

### 3. Initialize a New Shot
```bash
python3 pipeline.py init-shot shot-02
```

### 4. Run Pipeline
```bash
# Full execution (validate -> S1 -> S2 -> S3 -> S4)
make run
# or
python3 pipeline.py run --spec spec/shot-01.poster.json

# Clean build artifacts
make clean
```

---

## Reusable Agent Skill

This pipeline is packaged as a reusable Agent Skill located at:
- Repository source: `skills/code-driven-shot-pipeline/`
- Installed agent skill: `/Users/kelen/.agents/skills/code-driven-shot-pipeline/`
