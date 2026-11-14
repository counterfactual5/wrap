# Select the newest interpreter with version >= 3.10 (the engine uses
# int.bit_count()), unless the caller pins PY explicitly, e.g.
# `make PY=python3.11 verify`. Nothing here is device-specific: if none of
# these commands exists or qualifies, PY falls back to `python3`, and
# pipeline.py fails fast with a clear error instead of running on an old
# interpreter.
PY ?= $(shell for c in python3.13 python3.12 python3.11 python3.10 python3; do if command -v $$c >/dev/null 2>&1 && $$c -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"; then echo $$c; break; fi; done)
PY := $(if $(PY),$(PY),python3)

.PHONY: all test verify clean run

all:
	$(PY) pipeline.py run

run:
	$(PY) pipeline.py run

test:
	$(PY) pipeline.py test

verify:
	$(PY) pipeline.py test

clean:
	$(PY) pipeline.py clean
