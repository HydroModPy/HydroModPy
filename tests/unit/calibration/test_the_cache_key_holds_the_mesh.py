"""A cached cost must belong to the mesh it was computed on.

The evaluation cache is keyed on the parameters plus a context describing the
model. That context deliberately dropped ``mesh_catchment``, so two runs whose
only difference was the mesh shared their cache entries: the second one served
the first one's objectives without re-solving, on a different discretisation.

Declaring the requested mesh settings would not be enough either. gmsh is not
reproducible: the same request can produce a different triangulation, and the
stream-network criterion is normalised by cell size, so a cost from another mesh
is not the same number. The fingerprint therefore describes the mesh that was
BUILT, not the one that was asked for.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.runners.state import mesh_fingerprint


class _Mesh:
    def __init__(self, centroids: np.ndarray, *, structured: bool = True) -> None:
        self._centroids = centroids
        self.is_structured = structured
        self.ncol = 2

    def cell_centroids(self) -> np.ndarray:
        return self._centroids


def _ctx(mesh: object | None) -> SimpleNamespace:
    return SimpleNamespace(setup=SimpleNamespace(mesh_planar=mesh, mesh_summary=None))


_A = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [10.0, 10.0]], dtype=float)
_B = np.array([[0.0, 0.0], [5.0, 0.0], [0.0, 5.0], [5.0, 5.0]], dtype=float)


class TestItDescribesTheMeshThatWasBuilt:
    def test_a_mesh_yields_a_fingerprint(self) -> None:
        found = mesh_fingerprint(_ctx(_Mesh(_A)))

        assert found is not None
        assert found["n_cells"] == 4

    def test_two_different_meshes_do_not_share_a_fingerprint(self) -> None:
        first = mesh_fingerprint(_ctx(_Mesh(_A)))
        second = mesh_fingerprint(_ctx(_Mesh(_B)))

        assert first != second

    def test_the_same_mesh_yields_the_same_fingerprint(self) -> None:
        first = mesh_fingerprint(_ctx(_Mesh(_A)))
        second = mesh_fingerprint(_ctx(_Mesh(_A.copy())))

        assert first == second

    def test_a_reordered_mesh_is_a_different_mesh(self) -> None:
        """Cell order is the solver's own indexing; a different order is not the same grid."""
        reordered = _A[[1, 0, 3, 2]]

        assert mesh_fingerprint(_ctx(_Mesh(_A))) != mesh_fingerprint(_ctx(_Mesh(reordered)))

    def test_no_mesh_yields_nothing_rather_than_a_constant(self) -> None:
        """A lumped model has no mesh; keying on a placeholder would be a lie."""
        assert mesh_fingerprint(_ctx(None)) is None


class TestItReachesTheCacheKey:
    def test_the_context_carries_it(self) -> None:
        import inspect

        from hydromodpy.calibration.runners import state

        source = inspect.getsource(state.build_cache_context)

        assert "mesh_fingerprint" in source

    def test_two_meshes_give_two_different_hashes(self) -> None:
        from hydromodpy.calibration.optim.cache import params_hash

        values = {"K": 1e-5}
        first = params_hash(values, context={"mesh": mesh_fingerprint(_ctx(_Mesh(_A)))})
        second = params_hash(values, context={"mesh": mesh_fingerprint(_ctx(_Mesh(_B)))})

        assert first != second

    def test_the_requested_settings_alone_would_not_have_caught_it(self) -> None:
        """Same request, different triangulation: only the built mesh separates them."""
        from hydromodpy.calibration.optim.cache import params_hash

        requested = {"mesh_catchment": {"zone_meshing": {"global_size": 250.0}}}
        assert params_hash({"K": 1e-5}, context=requested) == params_hash(
            {"K": 1e-5}, context=requested
        )
