"""A mesh request names the earlier runs its size field read, and hashes them.

A request that reads no run keeps the hash the code gave it before the runs
were hashed, so the meshes cached for every existing project stay valid.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.request import LineFamilySpec, MeshRequest, RasterGridSpec, SizeField

_WKT = 'PROJCS["RGF93 / Lambert-93"]'

HASH_WITHOUT_RUNS = "5e5315bbed593615f48b1fd3fe18637a5afffe674fef6914f0e606274e36a1f6"
"""The hash of :func:`_request` computed with the request of 8071ff47f, which hashed no run."""


def _request(**overrides: object) -> MeshRequest:
    grid = RasterGridSpec(
        xmin=1000.0,
        xmax=1100.0,
        ymin=2000.0,
        ymax=2050.0,
        dx=10.0,
        dy=10.0,
        nrow=5,
        ncol=10,
        crs_wkt=_WKT,
    )
    members: dict[str, object] = {
        "domain": box(1000.0, 2000.0, 1100.0, 2050.0),
        "crs_wkt": _WKT,
        "grid": grid,
        "nominal_size_m": 20.0,
        "lines": (LineFamilySpec("rivers", "cell", (LineString([(1000, 2010), (1100, 2040)]),)),),
        "size_field": SizeField(np.full((5, 10), 20.0), grid),
        "seed": 3,
        "options": {"seeds": "generated"},
    }
    members.update(overrides)
    return MeshRequest(**members)


def test_a_request_that_reads_no_run_keeps_its_hash() -> None:
    assert _request().source_runs == ()
    assert _request().canonical_hash() == HASH_WITHOUT_RUNS
    assert _request(source_runs=[]).canonical_hash() == HASH_WITHOUT_RUNS


def test_the_runs_are_hashed_as_a_sorted_set() -> None:
    request = _request(source_runs=("b" * 32, "a" * 32, "b" * 32))

    assert request.source_runs == ("a" * 32, "b" * 32)
    assert request.canonical_hash() == _request(source_runs=["a" * 32, "b" * 32]).canonical_hash()
    assert request.canonical_hash() != HASH_WITHOUT_RUNS
    assert request.canonical_hash() != _request(source_runs=("a" * 32,)).canonical_hash()


@pytest.mark.parametrize("runs", ["abc", ("",), (" ",), (3,)])
def test_a_run_that_is_not_a_sim_id_is_refused(runs: object) -> None:
    with pytest.raises(MeshRequestError, match="source_runs"):
        _request(source_runs=runs)
