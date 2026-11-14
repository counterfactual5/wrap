"""The spec contract, one module per concern.

- `constants`   the value sets a spec may use
- `naming`      names that reach the filesystem
- `channels`    per-layer channels (anim, gait, spring, combat, captions)
- `layers`      per-layer field validation
- `shot`        the shot-level `validate` entry point
- `timeline`    the multi-shot timeline file
- `resolution`  deriving canvas geometry (joints, pivots) from source images
- `state`       carrying a shot's end state into the next
- `loader`      loading + validating a spec from disk

Use this package or its defining submodules for spec imports. The vocabulary
is defined in `constants`, shot validation in `shot`, and timeline validation
in `timeline`; the package re-exports their public names below.
"""
from .channels import (
    validate_anim,
    validate_captions_against_voiceover,
    validate_combat,
    validate_gait,
    validate_spring,
)
from .constants import (
    ANIM_CHANNELS,
    ANIM_EASES,
    BLENDS,
    CARD_TYPES,
    DRAWS,
    GAIT_MODES,
    HEX,
    HUD_TYPES,
    LAYER_ROLES,
    LAYER_TYPES,
    METRICS,
    NAME_RE,
    SPRING_CHANNELS,
    VIDEO_RATIOS,
    ZOOMABLE_CODE_DRAWS,
)
from .layers import validate_layer, validate_puppet_topology, zoom_supported
from .loader import load_spec
from .naming import hex_rgb, valid_name
from .resolution import PIVOT_JOINT_TOL, resolve_joints
from .shot import gate_of, validate
from .state import carry_state_from
from .timeline import VALID_BEATS, validate_timeline

__all__ = [
    "ANIM_CHANNELS",
    "ANIM_EASES",
    "BLENDS",
    "CARD_TYPES",
    "DRAWS",
    "GAIT_MODES",
    "HEX",
    "HUD_TYPES",
    "LAYER_ROLES",
    "LAYER_TYPES",
    "METRICS",
    "NAME_RE",
    "PIVOT_JOINT_TOL",
    "SPRING_CHANNELS",
    "VALID_BEATS",
    "VIDEO_RATIOS",
    "ZOOMABLE_CODE_DRAWS",
    "carry_state_from",
    "gate_of",
    "hex_rgb",
    "load_spec",
    "resolve_joints",
    "valid_name",
    "validate",
    "validate_anim",
    "validate_captions_against_voiceover",
    "validate_combat",
    "validate_gait",
    "validate_layer",
    "validate_puppet_topology",
    "validate_spring",
    "validate_timeline",
    "zoom_supported",
]
