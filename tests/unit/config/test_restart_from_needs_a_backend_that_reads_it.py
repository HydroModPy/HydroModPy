"""``[flow] restart_from`` is read by one backend, and the others said nothing.

A spin-up ends by handing back the Zarr of its converged state, and the whole
point of the exercise is to feed it to ``[flow] restart_from`` in the production
run. Only the MODFLOW 6 builders read that key. On MODFLOW-NWT and on Boussinesq
it was accepted and never looked at: the run started from the initial condition
the file declares, produced a perfectly plausible result, and nothing said the
antecedent had been dropped.

The support is declared as a solver capability rather than listed by name, so a
backend added later says what it can do instead of waiting to be added here.
"""

from __future__ import annotations

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import IncompatibleCapabilitiesError
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.solver.base.registry import capabilities
from hydromodpy.solver.base.solver_config import SolverConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

RESTART_CAPABILITY = "flow:restart"


def _base_kwargs(tmp_path) -> dict:
    return {
        "workflow": {"mode": "simulation"},
        "workspace": WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        "geographic": GeographicConfig(source_mode="synthetic"),
    }


def test_only_the_backend_that_reads_it_declares_the_capability() -> None:
    assert RESTART_CAPABILITY in capabilities("flow", "modflow6")
    assert RESTART_CAPABILITY not in capabilities("flow", "modflow_nwt")
    assert RESTART_CAPABILITY not in capabilities("flow", "boussinesq")


@pytest.mark.parametrize("backend", ["modflow_nwt", "boussinesq"])
def test_a_backend_that_cannot_restart_refuses_the_key(tmp_path, backend: str) -> None:
    with pytest.raises(IncompatibleCapabilitiesError) as caught:
        HydroModPyConfig(
            **_base_kwargs(tmp_path),
            solver=SolverConfig(backend={"backend": backend}),
            flow=FlowConfig(restart_from="runs/spinup_3/fields.zarr"),
        )

    message = str(caught.value)
    assert "restart_from" in message
    assert backend in message


def test_modflow6_accepts_it(tmp_path) -> None:
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        solver=SolverConfig(backend={"backend": "modflow6"}),
        flow=FlowConfig(restart_from="runs/spinup_3/fields.zarr"),
    )

    assert cfg.flow.restart_from == "runs/spinup_3/fields.zarr"


def test_leaving_it_unset_is_fine_on_any_backend(tmp_path) -> None:
    cfg = HydroModPyConfig(
        **_base_kwargs(tmp_path),
        solver=SolverConfig(backend={"backend": "boussinesq"}),
        flow=FlowConfig(),
    )

    assert cfg.flow.restart_from is None
