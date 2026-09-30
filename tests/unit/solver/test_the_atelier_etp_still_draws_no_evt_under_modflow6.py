"""A project like ``examples/projects/20_atelier_nancon`` gains no EVT package.

Its ``project.toml`` loads ``[data.etp]`` and lists ``"etp"`` in
``flow.active_sinks_sources``, exactly what MODFLOW-NWT reads for EVT; under
MODFLOW 6, without ``[flow.sinks_sources.recharge.soil]``, that ETP must still
go nowhere (only the warning is new).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.recharge import (
    ETP_IGNORED_OUTSIDE_SOIL_MODE,
    bind_soil_etp_from_flow,
    build_soil_evta_payload,
    resolve_deferred_soil_etp,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

_NCPL = 4


def _mesh() -> SolverMesh:
    top = np.array([[10.0, 11.0], [12.0, 13.0]], dtype=float)
    botm = np.array([[1.0, 1.0], [1.0, 1.0]], dtype=float)
    return SolverMesh.from_structured_arrays(nrow=2, ncol=2, top=top, botm=np.stack([botm]))


def test_a_loaded_etp_without_the_soil_marker_reaches_no_evta_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # SIM2 ETP loaded like [data.etp] would, same as an ordinary NWT EVT source.
    etp_cfg = SimpleNamespace(from_soil_reservoir=False, heterogeneous_source=object())
    model = SimpleNamespace(
        flow=SimpleNamespace(
            active_sinks_sources=["recharge", "etp"],
            sinks_sources={"etp": etp_cfg},
        ),
        ncpl=_NCPL,
        nper=1,
        model_name_mf6="atelier",
        drain_band_depth_m=0.0,
        solver_mesh=_mesh(),
        time_grid=None,
    )

    with caplog.at_level(logging.WARNING):
        bind_soil_etp_from_flow(model)
        resolve_deferred_soil_etp(model)

    assert model._soil_etp_rate is None
    assert ETP_IGNORED_OUTSIDE_SOIL_MODE in caplog.text

    payload = build_soil_evta_payload(
        model,
        model.solver_mesh,
        ocean_support_mask=np.zeros(_NCPL, dtype=bool),
        stream_support_mask=np.zeros(_NCPL, dtype=bool),
        lake_cell_ids=[],
        drain_active=False,
        shared_dir=None,
    )

    assert payload is None
