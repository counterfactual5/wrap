"""Validate a shot spec with ``python -m core.spec [spec]``."""
import sys

from .loader import load_spec


def main():
    try:
        spec = load_spec(sys.argv[1] if len(sys.argv) > 1 else None)
    except ValueError as ex:
        print(ex)
        return 1
    print(f"spec ok: {spec['id']} {spec['canvas']['w']}x{spec['canvas']['h']} "
          f"{spec['durationInFrames']}f, {len(spec['layers'])} layers, "
          f"{len(spec['gates'])} gates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
