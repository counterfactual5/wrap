"""Sprite rigging, joint/pivot calibration, part splitting, and multi-pose derivation.

Stdlib-only pixel utilities for 2D sprite & skeletal choreography:
- `source_to_canvas_pivot`: maps source image pixel (sx, sy) to exact canvas [px, py]
  accounting for S2's aspect-preserving `contain` (`decrease` + `pad`) scaling.
- `inspect_sprite`: generates a visual coordinate ruler grid (`build/inspect_sprite_<asset>.png`)
  with bounding-box & joint crosshair markers so agents/authors never blind-guess pivots.
- `split_sprite`: separates a single character sprite into a parent body asset and an
  articulated child weapon/limb asset of identical dimensions (1:1 canvas alignment),
  preserving a rounded overlap joint cap at `joint=(jx, jy)` and cleaning the perimeter
  ring for `edge_key_purity = 1.0`.
- `unpack_kit`: automatically detects, crops, pads, and registers all modular components
  from a multi-part runner/kit sheet on solid key_color via connected-component BFS, and
  emits ready-to-paste Remotion layer JSON templates.
- `derive_poses_from_sheet`: slices a multi-pose horizontal sprite sheet (`cols=N`) into
  individual center-aligned pose assets registered in `manifest.json`.
"""
import math
import os

from core.runtime import manifest
from core.quality.pixels import edge_key_purity, read_rgb
from core.media.png import read_size, write_png
from core.runtime.config import ROOT
from core.spec.naming import hex_rgb

from .sprites import (
    source_to_canvas_pivot,
    clean_perimeter,
    sprite_bbox,
    inspect_sprite,
    split_sprite,
    split_multi_sprite,
)
from .kits import (
    snap_socket_joint,
    extract_kit,
    unpack_kit,
)
from .poses import (
    derive_poses_from_sheet,
)
from .kinematics import (
    solve_2bone_ik,
    solve_leg_ground_lock,
    solve_spring_damper_track,
    eval_channel,
)
from .verification import (
    verify_puppet_rig,
    verify_combat_contact,
    verify_stage_blocking,
    _dominant_backdrop_at_frame,
    _extract_root_character_states,
    verify_shot_stagecraft,
    verify_timeline_continuity,
)
