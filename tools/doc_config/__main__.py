"""Entry point: ``python -m tools.doc_config``."""

from __future__ import annotations

from tools.doc_config.generate import generate_all


def main() -> int:
    written = generate_all()
    print(f"Wrote {len(written)} files under {written[0].parent}")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
