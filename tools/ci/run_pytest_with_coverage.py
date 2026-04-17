"""Run pytest under coverage using the repo's canonical source list."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.ci.coverage_helpers import coverage_include_patterns


def main(argv: list[str] | None = None) -> int:
    """Run pytest with coverage and return pytest's exit code."""
    import coverage
    import pytest

    cov = coverage.Coverage(
        config_file=False,
        data_suffix=True,
        include=coverage_include_patterns(),
    )
    cov.start()
    try:
        return int(pytest.main(list(sys.argv[1:] if argv is None else argv)))
    finally:
        cov.stop()
        cov.save()


if __name__ == "__main__":
    raise SystemExit(main())
