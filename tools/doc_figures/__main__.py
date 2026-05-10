"""Entry point: ``python -m tools.doc_figures``."""

from __future__ import annotations

from tools.doc_figures.generate import generate


def main() -> int:
    written = generate()
    print(f"Wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
