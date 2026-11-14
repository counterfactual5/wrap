"""Loading a spec from disk and validating it."""
import json
import os

from core.runtime.config import ROOT

from .resolution import resolve_joints
from .shot import validate


def load_spec(path=None):
    if not path:
        raise ValueError("An explicit spec path is required")
    with open(path) as f:
        spec = json.load(f)
    errs = validate(spec)
    if errs:
        raise ValueError("invalid spec:\n  " + "\n  ".join(errs))
    return resolve_joints(spec)
