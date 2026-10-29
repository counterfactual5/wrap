"""Step-1 fixture: hand-made white-background asset standing in for the generated one.
Registers it in the manifest as source=fixture (never overwrites a verified entry)."""
import os
import sys

from lib import manifest
from lib.draw import write_fixture
from schema import ROOT, load_spec

spec = load_spec()
for L in spec["layers"]:
    if L["type"] != "ai":
        continue
    rel = f"assets/{L['asset']}.png"
    if manifest.verified("assets", L["asset"]):
        print(f"skip {rel}: already frozen in manifest")
        continue
    write_fixture(os.path.join(ROOT, rel))
    row = manifest.register("assets", L["asset"], rel, source="fixture")
    print(f"wrote {rel} sha256={row['sha256'][:12]}")
sys.exit(0)
