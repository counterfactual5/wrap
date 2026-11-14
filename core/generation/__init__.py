"""Generation transport: the S1 implementation layer.

The stage script (stages/01_generate.py) owns the spec-driven orchestration;
everything that talks to the outside world lives here, one module per
concern:

* `connector.py`  the `mcode-tools` subprocess transport (shared plumbing)
* `images.py`     image generation, URL fetch, download, PNG normalization
* `uploads.py`    temp-URL upload and reference-image resolution
* `video.py`      asynchronous video submit / poll / download, clip duration
* `fixtures.py`   the zero-cost deterministic fixture builders

This package only depends on the low-level core modules (core.runtime.config,
core.runtime.manifest, core.generation.models, core.media, ...) — never on stages/.
"""
