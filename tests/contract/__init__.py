"""Cross-layer contract conformance tests.

These guard the boundary between the spec contract (`core/spec/constants.py`'s
`DRAWS`) and the Remotion renderer (`remotion/*.tsx` and `remotion/layers/`),
in both directions. `agreement.py` is a shared helper (not a test module)
imported by the test files in this package.
"""
