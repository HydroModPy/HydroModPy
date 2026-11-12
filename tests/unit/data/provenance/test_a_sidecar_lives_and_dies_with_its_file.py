"""A sidecar and its data file live and die together.

The cache removed a data file and left its ``<file>.json`` sidecar behind. The
orphan was then read as a data file by the next scan. Now a sidecar goes first,
and a sidecar left without its file is no row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.provenance.sidecars import CacheIndex, data_path_for_sidecar


def _recorded(data_root: Path, name: str = "geology_brgm_1m_abc.gpkg", **fields: object):
    variable = name.split("_")[0]
    path = data_root / variable / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")
    index = CacheIndex(data_root)
    fields = {"source": "brgm_1m", **fields}
    return index, index.record(path, variable=variable, **fields)


def _file_with_sidecar(folder: Path, name: str = "geology_brgm_1m_abc.gpkg") -> Path:
    _, row = _recorded(folder, name)
    return row.path


@pytest.mark.parametrize("name", ["foo.json", "foo.v1.2.json", "foo.gpkg", "foo.gpkg.bak"])
def test_other_names_are_not_sidecars(name: str) -> None:
    assert data_path_for_sidecar(Path("/d") / name) is None
