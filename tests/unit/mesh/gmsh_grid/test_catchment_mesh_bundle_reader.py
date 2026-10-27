"""The bundle format is versioned and its columns are documented in the reader.

Every bundle committed to the repository declares the version the reader reads,
holds every column the schema requires, and holds no column the schema does not
name. A writer that drifts from the documented format fails here.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    BUNDLE_COLUMNS,
    BUNDLE_SCHEMA_VERSION,
    OPTIONAL,
    load_catchment_mesh_bundle,
)

REPO = Path(__file__).resolve().parents[4]
COMMITTED = sorted(
    path.parent for path in (REPO / "validation_cases").rglob("mesh_bundles/*/metadata.json")
)


def _header(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as stream:
        return next(csv.reader(stream))


def _schema_name(column: str) -> str:
    return "n<k>" if re.fullmatch(r"n\d+", column) else column


def test_the_repository_commits_bundles():
    assert len(COMMITTED) >= 13


@pytest.mark.parametrize("bundle", COMMITTED, ids=lambda path: path.name)
def test_a_committed_bundle_follows_the_documented_schema(bundle):
    metadata = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["bundle_schema_version"] == BUNDLE_SCHEMA_VERSION
    assert load_catchment_mesh_bundle(bundle).metadata_view.crs

    for filename, columns in BUNDLE_COLUMNS.items():
        path = bundle / filename
        if not path.exists():
            assert filename == "cell_geology_fractions.csv"
            continue
        header = {_schema_name(column) for column in _header(path)}
        required = {name for name, text in columns.items() if not text.startswith(OPTIONAL)}
        assert required <= header, f"{path} lacks {required - header}"
        assert header <= set(columns), f"{path} holds undocumented {header - set(columns)}"
