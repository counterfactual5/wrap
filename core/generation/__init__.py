"""Generation transport: the S1 implementation layer.

The stage script (stages/01_generate.py) owns the spec-driven orchestration;
everything that talks to the outside world lives here, one module per
concern:

* `connector.py`  the `mcode-tools` subprocess transport (shared plumbing)
* `images.py`     image generation, URL fetch, download, PNG normalization
* `uploads.py`    temp-URL upload and reference-image resolution (frozen
                  manifest entries only — no code-pattern fallbacks)
* `video.py`      asynchronous video submit / poll / download, clip duration
* `fixtures.py`   compatibility tombstone only; no asset generation

The pipeline ships no built-in model catalog: capabilities are declared by
the environment (POSTER_MODELS_JSON / POSTER_IMAGE_CAPABILITIES_JSON, read
at import time by `models.py`). The connector is a transport adapter, not a
model-discovery mechanism.

This package only depends on the low-level core modules (core.runtime.config,
core.runtime.manifest, core.generation.models, core.media, ...) — never on stages/.
"""
