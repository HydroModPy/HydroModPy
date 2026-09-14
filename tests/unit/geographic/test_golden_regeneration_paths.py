"""The one-command golden regeneration helper must name files that exist.

``update_geographic_goldens.py`` hardcodes the list of tests it re-runs with
``--update-goldens``. Nothing checked that list, so it drifted: it named two
files that never existed in this checkout and one that had moved to the
regression tier. The command still exited 0-ish and regenerated nothing, which
is the worst way for a golden helper to fail.

Same shape as ``tests/unit/architecture/test_tolerances_single_source.py``:
a cheap gate that keeps a hand-maintained list tied to the tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.spatial.geographic.cases.update_geographic_goldens import GOLDEN_TEST_PATHS

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_the_helper_names_at_least_one_test() -> None:
    assert GOLDEN_TEST_PATHS


@pytest.mark.parametrize("relative_path", GOLDEN_TEST_PATHS)
def test_every_listed_golden_test_exists(relative_path: str) -> None:
    assert (REPO_ROOT / relative_path).is_file(), (
        f"update_geographic_goldens.py lists {relative_path}, which is not in the tree. "
        "Either the test moved and the list was not updated, or the list is stale."
    )


def test_every_listed_test_actually_consumes_the_update_goldens_flag() -> None:
    """A file in the list that never reads ``update_goldens`` regenerates nothing."""
    for relative_path in GOLDEN_TEST_PATHS:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "update_goldens" in source, (
            f"{relative_path} is listed for regeneration but never uses the "
            "update_goldens fixture, so --update-goldens is a no-op for it"
        )
