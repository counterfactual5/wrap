"""Rig alignment, combat contact, blocking, and stage continuity checks."""
from .puppet import verify_puppet_rig
from .combat import verify_combat_contact
from .blocking import verify_stage_blocking
from .stagecraft import (
    _dominant_backdrop_at_frame,
    _extract_root_character_states,
    verify_shot_stagecraft,
)
from .continuity import verify_timeline_continuity
