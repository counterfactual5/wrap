"""S1: Generation stage.
Contract:
- Reads: spec/shot-01.poster.json, spec/style.json, manifest.json
- Writes: assets/<asset>.png, manifest.json
- Exit code: 0 = all assets ready and verified, 1 = generation/download failure.
- Invariant: Generation is not re-entrant (no seed in API). If an asset is already verified in manifest.json,
  it is reused. Pass --force to explicitly re-generate.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request

from lib import manifest
from schema import ROOT, load_spec


def build_prompt(style):
    fields = style.get("promptFields", {})
    parts = []
    for key in ("subject", "composition", "background", "exclude"):
        if key in fields and fields[key].strip():
            parts.append(fields[key].strip())
    return ", ".join(parts)


def call_generate_image(prompt, asset_name, aspect_ratio="16:9", resolution="2K"):
    tmp_dir = os.path.join(ROOT, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    gen_file = os.path.join(tmp_dir, "gen.json")
    payload = {
        "requests": [
            {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "output_file": asset_name
            }
        ]
    }
    with open(gen_file, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Calling connector__matrix__generate_image with prompt:\n  {prompt}")
    cmd = ["mcode-tools", "connector", "call", "connector__matrix__generate_image", "--args-file", gen_file]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"mcode-tools connector call failed (code {proc.returncode}):\n{proc.stderr}")

    try:
        data = json.loads(proc.stdout)
    except Exception as ex:
        raise RuntimeError(f"Failed to parse connector response as JSON:\n{proc.stdout}") from ex

    # Expected: data contains success_items: [{"node_id": "...", "file_name": "..."}]
    success_items = data.get("success_items") or []
    if not success_items:
        raise RuntimeError(f"No success_items in response:\n{json.dumps(data, indent=2)}")

    node_id = success_items[0].get("node_id")
    if not node_id:
        raise RuntimeError(f"Missing node_id in success_items:\n{success_items[0]}")

    print(f"Generation succeeded, node_id={node_id}")
    return node_id


def fetch_asset_url(node_id):
    cmd = ["mcode-tools", "get-asset-url", str(node_id)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"mcode-tools get-asset-url failed:\n{proc.stderr}")

    out = proc.stdout.strip()
    if out.startswith("{"):
        try:
            d = json.loads(out)
            return d.get("url") or d.get("asset_url") or out
        except Exception:
            pass
    return out


def download_file(url, target_path):
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    print(f"Downloading asset to {target_path} ...")
    urllib.request.urlretrieve(url, target_path)


def main():
    parser = argparse.ArgumentParser(description="S1: Generate assets")
    parser.add_argument("--force", action="store_true", help="Force re-generation even if manifest entry exists")
    parser.add_argument("--fixture", action="store_true", help="Use deterministic code fixture instead of API")
    args = parser.parse_args()

    spec = load_spec()
    style_path = os.path.join(ROOT, spec.get("style", "spec/style.json"))
    style = {}
    if os.path.exists(style_path):
        with open(style_path) as f:
            style = json.load(f)

    prompt = build_prompt(style)

    for L in spec["layers"]:
        if L["type"] != "ai":
            continue
        asset = L["asset"]
        rel = f"assets/{asset}.png"
        target_path = os.path.join(ROOT, rel)

        if not args.force and manifest.verified("assets", asset):
            print(f"reuse {asset} (frozen in manifest, sha256 verified)")
            continue

        if args.fixture:
            from lib.draw import write_fixture
            write_fixture(target_path)
            row = manifest.register("assets", asset, rel, source="fixture")
            print(f"Registered fixture {rel} sha256={row['sha256'][:12]}")
            continue

        # Real generation via connector
        node_id = call_generate_image(prompt, asset)
        url = fetch_asset_url(node_id)
        download_file(url, target_path)

        # Register in manifest
        row = manifest.register("assets", asset, rel, source="ai-generated", node_id=node_id, prompt=prompt)
        print(f"Registered {rel} sha256={row['sha256'][:12]}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        print(f"S1 ERROR: {ex}", file=sys.stderr)
        sys.exit(1)
