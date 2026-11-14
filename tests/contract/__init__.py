"""Cross-layer contract conformance tests.

These guard the boundary between the spec contract (`core/spec/constants.py`'s
`LAYER_TYPES`, with `DRAWS` as the empty removed vocabulary) and the Remotion
renderer (`remotion/`), in both directions. `agreement.py` is a shared helper
(not a test module) imported by the test files in this package.
"""
