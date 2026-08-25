"""The derived release field must sum every path out of the aquifer.

Two code paths compute a quantity called ``release_flux``: the calibration
extractor, which unions the packages as it reads the binary budget, and this
one, which sums what the run persisted. They must mean the same thing.

Measured on the Nancon with the streams in SFR: 1.3276 of the 2.1018 m3/s left
through ``stream`` and 0.7986 through ``drain``, and the derived field held the
0.7986 alone. Every figure and every post-hoc analysis then read dry land over
63 per cent of the outgoing water, exactly where a stream-network criterion aims.
"""

from __future__ import annotations

import numpy as np
import pytest

zarr = pytest.importorskip("zarr")

from hydromodpy.simulation.extraction.derivation.derived import (  # noqa: E402
    _SURFACE_RELEASE_BUDGETS,
    _release_flux_stack,
)

N_CELLS = 6


class _Store:
    """Minimal stand-in for the run store the derivation reads."""

    def __init__(self, root) -> None:
        self._root = root


def _budget(tmp_path, components: dict[str, np.ndarray]):
    """Write a budget group holding one signed stack per component."""
    root = zarr.open_group(str(tmp_path / "fields.zarr"), mode="w")
    budget = root.create_group("budget")
    for name, values in components.items():
        arr = np.asarray(values, dtype="float64").reshape(1, 1, N_CELLS)
        budget.create_array(name, shape=arr.shape, dtype="float64")[:] = arr
    return root


@pytest.fixture
def stack(monkeypatch, tmp_path):
    """Return a caller that builds the stack over a synthetic budget group."""
    import contextlib

    from hydromodpy.simulation.extraction.derivation import derived as module

    def build(components: dict[str, np.ndarray]) -> np.ndarray:
        root = _budget(tmp_path, components)

        @contextlib.contextmanager
        def _fake_root(_store, _sim_id):
            yield root

        monkeypatch.setattr(module, "_zarr_root", _fake_root)
        return _release_flux_stack("sim", _Store(root), 1, N_CELLS)

    return build


# MODFLOW signs a budget from the aquifer's point of view: negative leaves it.
LEAVING = -1.0
ENTERING = 1.0


def test_the_drain_alone_is_read_when_it_is_the_only_path(stack) -> None:
    out = stack({"drain": [LEAVING * 2.0, 0.0, LEAVING * 1.0, 0.0, 0.0, 0.0]})

    assert out.sum() == pytest.approx(3.0)


def test_a_stream_exchange_joins_the_drain(stack) -> None:
    out = stack(
        {
            "drain": [LEAVING * 2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "stream": [0.0, LEAVING * 5.0, 0.0, 0.0, 0.0, 0.0],
        }
    )

    assert out.sum() == pytest.approx(7.0), "the stream package is a path out"
    assert out[0, 0] == pytest.approx(2.0)
    assert out[0, 1] == pytest.approx(5.0)


def test_a_cell_served_by_two_paths_carries_their_total(stack) -> None:
    out = stack(
        {
            "drain": [LEAVING * 2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "stream": [LEAVING * 3.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
    )

    assert out[0, 0] == pytest.approx(5.0)


def test_water_entering_the_aquifer_releases_nothing(stack) -> None:
    # A losing reach, an infiltrating boundary: the clamp is the same rule the
    # drain gets, so it cannot cancel a release elsewhere.
    out = stack(
        {
            "drain": [LEAVING * 2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "stream": [0.0, ENTERING * 9.0, 0.0, 0.0, 0.0, 0.0],
        }
    )

    assert out.sum() == pytest.approx(2.0)
    assert out[0, 1] == pytest.approx(0.0)


def test_a_lake_exchange_is_a_path_out_too(stack) -> None:
    out = stack({"lake": [LEAVING * 4.0, 0.0, 0.0, 0.0, 0.0, 0.0]})

    assert out.sum() == pytest.approx(4.0)


def test_a_run_with_no_release_path_at_all_is_refused(stack) -> None:
    with pytest.raises(KeyError, match="No release budget field"):
        stack({"recharge": [1.0] * N_CELLS})


def test_a_component_that_is_not_a_release_path_is_ignored(stack) -> None:
    out = stack(
        {
            "drain": [LEAVING * 2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "recharge": [1.0] * N_CELLS,
            "storage_sy": [LEAVING * 100.0] * N_CELLS,
        }
    )

    assert out.sum() == pytest.approx(2.0), "storage and recharge are not paths out"


def test_each_declared_path_carries_the_sign_of_its_convention() -> None:
    # MODFLOW signs from the aquifer's point of view; the Boussinesq surface
    # excess is already an outflow. One clamp for both silently dropped a half.
    assert _SURFACE_RELEASE_BUDGETS == {"stream": -1.0, "lake": -1.0, "surface_excess": 1.0}


def test_the_boussinesq_excess_keeps_its_own_convention(stack) -> None:
    out = stack({"surface_excess": [3.0, 0.0, 0.0, 0.0, 0.0, 0.0]})

    assert out.sum() == pytest.approx(3.0), "a positive surface excess is an outflow"
