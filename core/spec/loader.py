"""Loading a spec from disk and validating it."""
import json

from .resolution import resolve_joints
from .shot import validate


def load_spec(path=None):
    if not path:
        raise ValueError("An explicit spec path is required")
    with open(path) as f:
        spec = json.load(f)
    try:
        errs = validate(spec)
    except (TypeError, AttributeError, KeyError, IndexError) as ex:
        # A spec is hand-written, so a wrong type must read as "invalid spec",
        # not as a traceback from inside the validator. The original error is
        # chained, so the cause is still visible to whoever debugs it.
        raise ValueError(f"invalid spec: {type(ex).__name__}: {ex}") from ex
    if errs:
        raise ValueError("invalid spec:\n  " + "\n  ".join(errs))
    return resolve_joints(spec)
