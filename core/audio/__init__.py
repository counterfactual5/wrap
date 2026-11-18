"""Audio generation and mixing utilities for the code-driven video pipeline.

Split into focused submodules (functions and behavior unchanged):
- tts: Neural text-to-speech with natural cadence + broadcast mastering, fallback to local TTS
- mastering: Two-pass EBU R128 loudness normalization
- captions: Frame-accurate caption clause timing from TTS boundaries
- shot: Per-shot preparation (synthesize, master, mix to exact duration) and silence intent
- sync: Aligns shot durationInFrames and captions items to TTS speech timings
- metrics: Silence / loudness / A-V duration / punch detection measurements

The public API is re-exported here so `from core.audio import X` keeps working.
"""
from core.audio.tts import (
    _download_edge_tts,
    _download_neural_tts,
    synthesize_voiceover_with_timings,
    get_audio_duration,
    synthesize_voiceover,
)
from core.audio.mastering import run_two_pass_loudnorm
from core.audio.captions import _split_sentence_clauses, clauses_from_boundaries
from core.audio.shot import prepare_shot_audio, shot_is_intentionally_silent
from core.audio.sync import (
    _build_clause_anchors, _norm_cjk, _rescale_frame, _rescale_spec_timings,
    sync_spec_audio,
)
from core.audio.metrics import (
    detect_audio_punches,
    measure_audio_loudness,
    measure_audio_loudness_detail,
    measure_audio_silence,
    measure_av_durations,
)
