"""Loading a spec from disk and validating it."""
import json
import os

from core.runtime.config import ROOT

from .resolution import resolve_joints
from .shot import validate


def load_spec(path=None):
    path = path or os.path.join(ROOT, "tests", "fixtures", "shot-01.poster.json")
    with open(path) as f:
        spec = json.load(f)
    errs = validate(spec)
    if errs:
        raise ValueError("invalid spec:\n  " + "\n  ".join(errs))
    return resolve_joints(spec)
