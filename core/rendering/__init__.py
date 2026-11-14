"""S3 rendering: Remotion timeline parity, <Video>-semantics frame
extraction, the render driver, and the bit-exact mp4 encode.

The built-in Quartz design backend (renderers/quartz) has been removed: the
engine ships a pipeline, not artwork, and projects bring their own renderers.
`core.rendering.quartz._render_quartz_fallback` stays as an explicit error for
old call sites.

Split into focused submodules out of stages/03_compose.py, which keeps only
main() and the flow:
- timeline:      JS-parity rounding, a video layer's Remotion timeline, atempo factors
- video_frames:  frame extraction with trim / playbackRate / loop / fit and a
                 transparent fill for unmounted windows
- remotion:      props assembly and the `npx remotion render` driver
- encoding:      audio ownership resolution and the mp4 encode

The public API is re-exported here so `from core.rendering import X` keeps
working. Dependency mocks must target the defining submodule, not this
facade.
"""
from core.rendering.timeline import _js_round, atempo_chain, video_timeline
from core.rendering.video_frames import (
    _extract_video_frames,
    _write_solid_png,
)
from core.rendering.quartz import _render_quartz_fallback
from core.rendering.remotion import build_props, render_remotion
from core.rendering.encoding import encode_mp4, video_audio_source
