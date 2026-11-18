"""Subprocess timeouts, and the one place that turns a hang into an error.

Every external command the engine runs can fail in two ways: it can exit
non-zero (a normal failure the caller reports), or it can hang forever (a
wedged ffmpeg on a dead mount, a `say` waiting on a stuck audio device, a
render whose browser never comes back). The second kind has no exit code and
no output — the pipeline just stops, silently, holding the process.

So every call gets a bounded budget, and a timeout is raised as a
RuntimeError that names the command that hung. The budgets live here, in one
place, so "how long may a render take?" is one question with one answer.

The budgets are deliberately coarse — they exist to turn "hangs forever"
into "fails with a diagnosis", not to police performance.

Two tiers:

* LOCAL — ffmpeg/ffprobe on local files. These are fast and deterministic;
  a generous ceiling catches a wedged disk, not slow work.
* EXTERNAL — commands that reach outside the machine (a renderer, a
  network TTS fetch). These get their own budget because their duration
  depends on the work, not on the file size.
"""
import subprocess


# --- local media tools -------------------------------------------------------
# A local transcode of a few seconds of media takes well under a second;
# a minute of slack still leaves a wedged disk detectable.
LOCAL_TOOL_TIMEOUT = 300

# Probing a file's metadata (ffprobe) is near-instant.
PROBE_TIMEOUT = 60

# Freezing one frame out of a rendered clip: ffmpeg seeks, decodes one
# frame and writes it.
EXTRACT_FRAME_TIMEOUT = 180


# --- external / interactive tools --------------------------------------------
# A renderer renders a whole shot: the budget has to cover the shot's real
# duration, so the caller derives it (see render_timeout_seconds) rather
# than taking a fixed number.
RENDER_BASE_TIMEOUT = 900

# macOS `say` synthesizes a paragraph in seconds; a long narration takes
# longer, and the caller scales with the text length (see say_timeout).
SAY_BASE_TIMEOUT = 120
SAY_SECONDS_PER_CHAR = 0.05

# A stage subprocess is a whole pipeline stage: it may render a shot, so its
# budget is the render budget plus room for the rest of the stage.
STAGE_TIMEOUT = 3600

# Fetching a TTS audio file over the network.
NETWORK_FETCH_TIMEOUT = 120

# Asking macOS for its installed voice list is a local, instant query.
VOICE_LIST_TIMEOUT = 20


def render_timeout_seconds(shot_seconds, per_second=4.0, floor=RENDER_BASE_TIMEOUT):
    """A render budget for a shot of `shot_seconds` length.

    Remotion renders far slower than real time (it drives a headless
    browser), and the first run of a shot also pays for bundling. The
    budget scales with the shot so a long film is not cut off mid-render,
    and keeps a floor so a short shot still gets room for the bundle step.

    `floor` is the minimum budget; `per_second` is the extra allowance per
    second of shot length.
    """
    if shot_seconds is None or shot_seconds <= 0:
        return floor
    return int(max(floor, floor + float(shot_seconds) * per_second))


def say_timeout(text):
    """A `say` budget for `text`.

    The narrator's length is the only thing that decides how long the
    synthesis takes, so the budget follows the text.
    """
    if not text:
        return SAY_BASE_TIMEOUT
    return int(SAY_BASE_TIMEOUT + len(str(text)) * SAY_SECONDS_PER_CHAR)


def _command_name(cmd):
    """The command's name, for an error message a human can act on."""
    if isinstance(cmd, (list, tuple)) and cmd:
        return str(cmd[0])
    return str(cmd)


def run_with_timeout(cmd, timeout, *, check=False, capture_output=False,
                     text=False, **kwargs):
    """`subprocess.run` with a bounded budget and a legible timeout error.

    A timeout raises RuntimeError naming the command and the budget, so the
    caller can say which step wedged. A non-zero exit is left alone for the
    caller to handle (or raises CalledProcessError when `check=True`), which
    keeps the existing error handling intact.
    """
    try:
        return subprocess.run(
            cmd, check=check, capture_output=capture_output, text=text,
            timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as ex:
        raise RuntimeError(
            f"{_command_name(cmd)} timed out after {timeout}s — the command "
            f"did not finish. If it is a render, the shot may be longer than "
            f"the budget allows; if it is a media tool, the input file or "
            f"the disk may be wedged.\n"
            f"  command: {' '.join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else cmd}"
        ) from ex
