"""Compatibility entry point for the removed built-in Quartz design backend."""


def _render_quartz_fallback(spec, out_dir, shot_id):
    """Fail without touching output; project artwork has no built-in substitute."""
    raise RuntimeError("已移除内置Quartz设计后端，使用Remotion或项目后端")
