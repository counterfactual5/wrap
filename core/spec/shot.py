"""Shot-level validation: the spec as a whole.

`validate` is the entry point every caller uses — it checks the shot's own
fields, then each layer through `core.spec.layers`, then the relationships
between layers (parents, combat) and the gates.
"""
from .channels import validate_combat
from .constants import METRICS
from .layers import validate_layer, validate_puppet_topology
from .naming import valid_name


def validate(spec):
    errs = []
    e = errs.append
    for k in ("id", "canvas", "fps", "durationInFrames", "layers", "gates"):
        if k not in spec:
            e(f"missing '{k}'")
    if errs:
        return errs
    # The shot id names directories under build/ and public/ (prepared clips
    # are staged there), so it must not be able to walk out of them.
    if not valid_name(spec["id"]):
        e(f"id must be a letters/digits/._- string (got {spec['id']!r}); it "
          f"names directories under build/ and public/")
    W, H = spec["canvas"].get("w"), spec["canvas"].get("h")
    if not (isinstance(W, int) and isinstance(H, int) and W > 0 and H > 0):
        e("canvas.w/h must be positive ints")
    if not (isinstance(spec["fps"], int) and spec["fps"] > 0):
        e("fps must be a positive int")
    if not (isinstance(spec["durationInFrames"], int) and spec["durationInFrames"] > 1):
        e("durationInFrames must be an int > 1")
    ids, zs = set(), set()
    layer_by_id = {x.get("id"): x for x in spec["layers"] if isinstance(x, dict) and x.get("id")}
    ai_asset_set = {x.get("asset") for x in spec["layers"] if isinstance(x, dict) and x.get("type") == "ai" and x.get("asset")}

    for L in spec["layers"]:
        validate_layer(L, spec, ids, zs, layer_by_id, ai_asset_set, errs)
    # Validate parent references across layers (no missing parent, no self/cycle).
    parent_map = {L.get("id"): L.get("parent") for L in spec["layers"] if L.get("parent") is not None}
    for lid, par in parent_map.items():
        if not isinstance(par, str) or par not in ids:
            e(f"{lid}: parent {par!r} must reference an existing layer id in this shot")
        elif par == lid:
            e(f"{lid}: parent cannot reference itself")
        else:
            seen = {lid}
            cur = par
            while cur in parent_map:
                if cur in seen:
                    e(f"{lid}: cyclic parent chain involving {cur!r}")
                    break
                seen.add(cur)
                cur = parent_map[cur]
    punches = spec.get("punches")
    if punches is not None:
        if not (isinstance(punches, list) and all(isinstance(v, int) and 0 <= v for v in punches)):
            e("punches must be a list of non-negative frame ints")
    if "vibe_grade" in spec and not isinstance(spec["vibe_grade"], bool):
        e("vibe_grade must be a boolean")
    if "vibe" in spec and not isinstance(spec["vibe"], bool):
        # The renderer opts out with a strict `vibe !== false`, so a
        # non-boolean value would run the opposite of what the author wrote.
        e("vibe must be a boolean")
    if "ambient" in spec and not isinstance(spec["ambient"], bool):
        e("ambient must be a boolean")
    if "audio" in spec and spec["audio"] is not None:
        if not isinstance(spec["audio"], dict):
            e("audio must be a dictionary")
        else:
            if "ambient" in spec["audio"] and not isinstance(spec["audio"]["ambient"], bool):
                e("audio.ambient must be a boolean")
            if "bgmOffset" in spec["audio"]:
                bo = spec["audio"]["bgmOffset"]
                if isinstance(bo, bool) or not isinstance(bo, (int, float)) or bo < 0:
                    e(f"audio.bgmOffset must be a non-negative number in seconds (got {bo!r})")
            if "voiceover" in spec["audio"] and spec["audio"]["voiceover"] is not None:
                if not isinstance(spec["audio"]["voiceover"], str):
                    e("audio.voiceover must be a string")
            if "bgm" in spec["audio"] and spec["audio"]["bgm"] is not None:
                if not isinstance(spec["audio"]["bgm"], str):
                    e("audio.bgm must be a string (preset name or audio file path)")
    if "combat" in spec and spec["combat"] is not None:
        validate_combat(spec["combat"], ids, errs)
    gids = set()
    for g in spec["gates"]:
        if g.get("id") in gids:
            e(f"duplicate gate id {g.get('id')}")
        gids.add(g.get("id"))
        if g.get("metric") not in METRICS:
            e(f"gate {g.get('id')}: unknown metric {g.get('metric')}")
        lo, hi = g.get("lo"), g.get("hi")
        if lo is None and hi is None:
            e(f"gate {g.get('id')}: needs lo and/or hi")
        if lo is not None and hi is not None and lo > hi:
            e(f"gate {g.get('id')}: lo > hi")
        # region: optional [y0, y1] canvas band excluded from motion metrics,
        # so a panning foreground cannot mask a static subject.
        r = g.get("region")
        if r is not None and not (isinstance(r, list) and len(r) == 2
                                  and all(isinstance(v, int) for v in r) and 0 <= r[0] < r[1] <= spec["canvas"]["h"]):
            e(f"gate {g.get('id')}: region must be [y0,y1] ints within canvas height")
    validate_puppet_topology(spec, errs)
    return errs


def gate_of(spec, metric):
    return next((g for g in spec["gates"] if g["metric"] == metric), None)
