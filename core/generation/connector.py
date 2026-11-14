"""The `mcode-tools` connector transport shared by image and video generation.

Every external call is bounded and retried here, so a hung or flaky backend
fails the stage instead of hanging the whole pipeline before its gates run.

Positioning: this module is a TRANSPORT ADAPTER — it moves JSON payloads and
files to and from a generation backend through the `mcode-tools` CLI. It
performs NO model or capability discovery: which models exist and what they
accept is declared explicitly by the environment (POSTER_MODELS_JSON,
POSTER_IMAGE_CAPABILITIES_JSON — see core/generation/models.py) or by the
call's own parameters. Do not read this transport as an auto-discovery
mechanism.
"""
import json
import os
import subprocess
import time

from core.runtime.config import ROOT

# Every external call is bounded: a hung backend must fail the stage instead
# of hanging the whole pipeline before its gates ever run.
CALL_TIMEOUT = 180

# The native backends are driven through the `mcode-tools` CLI. A missing CLI
# is the most common first-run failure, and the raw errno ("No such file or
# directory: 'mcode-tools'") tells the newcomer nothing — so the failure says
# what the CLI is, how to install it, and how to substitute the transport.
# (There is no fixture rehearsal mode to point at: the pipeline generates for
# real, or it does not run.)
CONNECTOR_MISSING_HELP = (
    "the connector CLI `mcode-tools` is not on PATH — the native generation "
    "backends (image / video) are driven through it.\n"
    "  * install it (it ships with the MCode runtime), or\n"
    "  * substitute the transport and register the asset by hand: see the "
    "Skill's 'Asset Transport' section (HF Spaces, public-domain sources; "
    "register with source= and credit=).\n"
    "Note: the connector is a transport adapter only — it does not discover "
    "models or capabilities. Declare what your backend supports with "
    "POSTER_MODELS_JSON / POSTER_IMAGE_CAPABILITIES_JSON (or pass explicit "
    "model/size parameters)."
)


def _run_connector(cmd, timeout=CALL_TIMEOUT):
    """Run one `mcode-tools` call. A missing CLI must say what to do next."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as ex:
        raise RuntimeError(
            f"mcode-tools not found: {ex}\n{CONNECTOR_MISSING_HELP}") from ex


def _connector_call(tool, payload, timeout=CALL_TIMEOUT, attempts=3):
    """Call one connector tool with a JSON payload, returning parsed JSON.

    Transient network faults (ECONNRESET, connect timeout, socket error) are
    common against the connector backend. The video poll in particular runs
    for minutes while the model works — a single dropped connection would
    throw away the whole wait — so the call is retried with a growing pause
    before it is reported as a failure."""
    tmp_dir = os.path.join(ROOT, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    args_file = os.path.join(tmp_dir, f"{tool.replace('__', '_')}.json")
    with open(args_file, "w") as f:
        json.dump(payload, f, indent=2)
    cmd = ["mcode-tools", "connector", "call", tool, "--args-file", args_file]
    last = ""
    for i in range(attempts):
        try:
            proc = _run_connector(cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            last = f"timed out after {timeout}s"
            proc = None
        if proc is not None and proc.returncode == 0:
            try:
                return json.loads(proc.stdout)
            except Exception as ex:
                raise RuntimeError(f"{tool} returned non-JSON output:\n{proc.stdout}") from ex
        if proc is not None:
            last = proc.stderr.strip() or f"exit {proc.returncode}"
        print(f"  {tool} attempt {i + 1}/{attempts} failed: {last}")
        if i < attempts - 1:
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{tool} failed after {attempts} attempts:\n{last}")
