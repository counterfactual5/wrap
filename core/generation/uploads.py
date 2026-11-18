"""Reference uploads: temp-URL hop and reference-image resolution.

The image backend takes references by URL only — it cannot read a local
path or a data URI. Image-to-image and video keyframes therefore need this
hop: resolve the reference to a verified local file, upload it, and hand the
returned temp_url to the backend.
"""
import json
import os
import subprocess
import time

from core.runtime import manifest
from core.runtime.config import ROOT
from core.generation.connector import CALL_TIMEOUT, _run_connector


def upload_temp_url(file_path, attempts=3):
    """Upload a local file and return its temporary URL.

    The image backend takes references by URL only — it cannot read a local
    path or a data URI. Image-to-image therefore needs this hop: upload the
    frozen source asset, then hand the returned temp_url to the backend.

    The connector provider is intermittently busy ("connector_busy"), and a
    single dropped upload would fail the whole stage over a condition that
    clears on its own. Retry with a growing pause, the way the asset-URL
    lookup and the connector call already do."""
    cmd = ["mcode-tools", "upload-temp-url", str(file_path)]
    last = ""
    for i in range(attempts):
        try:
            proc = _run_connector(cmd)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"upload of {file_path} timed out after {CALL_TIMEOUT}s")
        if proc.returncode == 0:
            break
        last = proc.stderr.strip() or f"exit {proc.returncode}"
        print(f"  upload attempt {i + 1}/{attempts} failed: {last}")
        if i < attempts - 1:
            time.sleep(2 * (i + 1))
    else:
        raise RuntimeError(
            f"mcode-tools upload-temp-url failed after {attempts} attempts:\n{last}")
    try:
        data = json.loads(proc.stdout)
    except Exception as ex:
        raise RuntimeError(
            f"upload-temp-url returned non-JSON output:\n{proc.stdout}") from ex
    url = data.get("temp_url") or data.get("url")
    if not url:
        raise RuntimeError(
            f"upload-temp-url returned no temp_url (keys: {sorted(data.keys())})")
    return url


def resolve_reference_image_path(ref_name, spec, style=None):
    """Resolve a reference image name to a VERIFIED FROZEN local PNG file path.

    Read-only: only entries already frozen in manifest.json are accepted —
    this function never draws, generates or pre-paints anything:
    1. A frozen asset in manifest['assets'] (AI-generated or manually
       registered, or referenced via an 'ai' layer's id / asset);
    2. An already-prepared image in manifest['prepared'] (frozen by S2).

    Code layers are rejected: the S1 transport no longer pre-draws code
    patterns (grid/dots/...) as references — no template fallback. A
    reference must point at a frozen image; generate or prepare it first,
    then re-run. The `style` argument stays for signature compatibility
    with callers that already pass it."""
    shot_id = spec["id"]
    row = manifest.verified("assets", ref_name)
    if row:
        return os.path.join(ROOT, row["path"]), row["path"]

    for layer in spec.get("layers", []):
        if not (isinstance(layer, dict) and layer.get("id") == ref_name):
            continue
        if layer.get("type") == "ai":
            ai_asset = layer.get("asset")
            if ai_asset:
                ai_row = manifest.verified("assets", ai_asset)
                if ai_row:
                    return os.path.join(ROOT, ai_row["path"]), ai_row["path"]
        if layer.get("type") == "code":
            raise RuntimeError(
                f"reference image {ref_name!r} points to a code layer "
                f"(draw={layer.get('draw')!r}); S1 no longer pre-draws code "
                f"patterns as references — register a frozen image asset "
                f"under {ref_name!r} (manifest 'assets'), or point the "
                f"layer's reference at a frozen asset instead")

    prep_row = manifest.verified("prepared", f"{shot_id}/{ref_name}")
    if prep_row:
        return os.path.join(ROOT, prep_row["path"]), prep_row["path"]

    raise RuntimeError(
        f"reference image {ref_name!r} is not a verified frozen image in the "
        f"manifest (assets/prepared) — generate or prepare it first, then "
        f"re-run; code-pattern fallbacks are not available")
