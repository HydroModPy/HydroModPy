"""The conductivity a MODFLOW 6 run was given survives the run.

MODFLOW writes its heads back out and its inputs never. The builder is the
only place the resolved property arrays exist, and the extractor reads a
folder, not a builder, so the two meet through a file left beside the model.
This pins that handshake: the name, the shape, and what the extractor refuses.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.build import (
    FLOW_PROPERTY_SIDECAR_SUFFIX,
    _save_flow_property_sidecar,
)
from hydromodpy.solver.modflow6.extractors.flow import _write_flow_properties

N_CELLS = 6
N_LAYERS = 2

MODEL_NAME = "canut_paper"


class _Sink:
    """Records what the extractor asked the Zarr store to write."""

    def __init__(self) -> None:
        self.written: dict[str, np.ndarray] = {}
        self.subgroups: set[str] = set()

    def write_static_field(self, variable: str, values: np.ndarray, *, subgroup: str) -> None:
        self.written[variable] = np.asarray(values)
        self.subgroups.add(subgroup)


def _model(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        full_path=str(tmp_path),
        model_output_name=MODEL_NAME,
        hk=np.full((N_LAYERS, N_CELLS), 2.0e-5),
        sy=np.full((N_LAYERS, N_CELLS), 0.01),
        ss=np.full((N_LAYERS, N_CELLS), 1.0e-6),
    )


def test_the_builder_leaves_one_file_named_after_the_model(tmp_path: Path) -> None:
    _save_flow_property_sidecar(_model(tmp_path))
    sidecars = list(tmp_path.glob(f"*{FLOW_PROPERTY_SIDECAR_SUFFIX}"))
    assert [path.name for path in sidecars] == [f"{MODEL_NAME}{FLOW_PROPERTY_SIDECAR_SUFFIX}"]


def test_the_extractor_persists_the_three_properties_under_derived(tmp_path: Path) -> None:
    _save_flow_property_sidecar(_model(tmp_path))
    sink = _Sink()
    _write_flow_properties(sink, tmp_path, n_cells=N_CELLS)

    assert set(sink.written) == {
        "hydraulic_conductivity",
        "specific_yield",
        "specific_storage",
    }
    assert sink.subgroups == {"derived"}
    assert sink.written["hydraulic_conductivity"].shape == (N_LAYERS, N_CELLS)
    assert sink.written["hydraulic_conductivity"] == pytest.approx(2.0e-5)


def test_a_property_that_does_not_match_the_mesh_is_left_out(tmp_path: Path) -> None:
    model = _model(tmp_path)
    model.sy = np.full((N_LAYERS, N_CELLS + 1), 0.01)
    _save_flow_property_sidecar(model)
    sink = _Sink()
    _write_flow_properties(sink, tmp_path, n_cells=N_CELLS)
    assert "specific_yield" not in sink.written
    assert "hydraulic_conductivity" in sink.written


def test_a_run_with_no_sidecar_writes_nothing_and_does_not_raise(tmp_path: Path) -> None:
    sink = _Sink()
    _write_flow_properties(sink, tmp_path, n_cells=N_CELLS)
    assert sink.written == {}
