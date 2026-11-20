"""The release flux (m3/s per cell) rebuilt on read sums every path out of the aquifer.

Two code paths compute a quantity called ``release_flux``: the calibration extractor, which unions
the packages as it reads the binary budget, and this one, which sums what the run persisted. They
must mean the same thing. On the Nancon with the streams in SFR, 1.3276 of the 2.1018 m3/s left
through ``stream`` and 0.7986 through ``drain``, and the derived field once held the 0.7986 alone.
"""

from __future__ import annotations

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from hydromodpy.core.budget.flux import SURFACE_RELEASE_BUDGETS  # noqa: E402
from hydromodpy.results.derive.virtual_fields import release_flux_rows  # noqa: E402

N_CELLS = 6


def release_over(tmp_path, components):
    # A budget group holding one signed stack per component.
    root = zarr.open_group(str(tmp_path / "fields.zarr"), mode="w")
    root.create_array("head", shape=(1, 1, N_CELLS), dtype="float64")
    budget = root.create_group("budget")
    for name, values in components.items():
        stack = np.asarray(values, dtype="float64").reshape(1, 1, N_CELLS)
        budget.create_array(name, shape=stack.shape, dtype="float64")[:] = stack
    return release_flux_rows(root, 0, 1)


# MODFLOW signs a budget from the aquifer's point of view: negative leaves it.
RELEASES = [
    pytest.param(
        {"drain": [-2.0, 0.0, -1.0, 0.0, 0.0, 0.0]},
        [2.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        id="drain alone",
    ),
    pytest.param(
        {"drain": [-2.0, 0.0, 0.0, 0.0, 0.0, 0.0], "stream": [0.0, -5.0, 0.0, 0.0, 0.0, 0.0]},
        [2.0, 5.0, 0.0, 0.0, 0.0, 0.0],
        id="stream joins the drain",
    ),
    pytest.param(
        {"drain": [-2.0, 0.0, 0.0, 0.0, 0.0, 0.0], "stream": [-3.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
        [5.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        id="two paths in one cell",
    ),
    # A losing reach or an infiltrating boundary is clamped like the drain,
    # so it cannot cancel a release elsewhere.
    pytest.param(
        {"drain": [-2.0, 0.0, 0.0, 0.0, 0.0, 0.0], "stream": [0.0, 9.0, 0.0, 0.0, 0.0, 0.0]},
        [2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        id="water entering releases nothing",
    ),
    pytest.param(
        {"lake": [-4.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
        [4.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        id="lake exchange",
    ),
    pytest.param(
        {
            "drain": [-2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "recharge": [1.0] * N_CELLS,
            "storage_sy": [-100.0] * N_CELLS,
        },
        [2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        id="storage and recharge are not paths out",
    ),
    pytest.param(
        {"surface_excess": [-3.0, 2.0, 0.0, 0.0, 0.0, 0.0]},
        [3.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        id="boussinesq excess follows the same sign",
    ),
]


@pytest.mark.parametrize(("components", "expected"), RELEASES)
def test_release_flux(tmp_path, components, expected):
    out = release_over(tmp_path, components)

    np.testing.assert_allclose(out[0], expected, atol=1e-12)


def test_no_release_path_is_refused(tmp_path):
    with pytest.raises(KeyError, match="No release budget field"):
        release_over(tmp_path, {"recharge": [1.0] * N_CELLS})


def test_every_path_out_is_declared():
    assert set(SURFACE_RELEASE_BUDGETS) == {
        "stream",
        "lake",
        "constant_head_stream",
        "surface_excess",
    }
