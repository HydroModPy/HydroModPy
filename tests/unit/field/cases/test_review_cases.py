"""The field demo runner, :mod:`hydromodpy.spatial.field.cases.square.run_field_demo`."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.field.cases.square.run_field_demo import run_field_demo_case
from hydromodpy.spatial.field.field_param import FieldParam
from hydromodpy.spatial.field.unit_square_mesh import FieldMeshSquare
from tests._helpers.field_cases import two_zone_square


def test_run_field_demo_case_writes_output_without_show(tmp_path: Path) -> None:
    values = {"granite": 10.0, "micaschists": 2.0}
    k = FieldParam(identifier="K", kind="heterogeneous", values_by_key=values, field_spatial_id="field_square")  # fmt: skip
    mesh = FieldMeshSquare.from_dict({"kind": "structured", "target_n_cells": 100})
    output = tmp_path / "field_case_demo.png"

    result = run_field_demo_case(
        field_param=k, mesh=mesh, field=two_zone_square(), output_file=output, show_plot=False
    )

    assert output.exists()
    assert result["mesh_kind"] == "structured"
    assert result["n_cells"] == mesh.n_cells
    assert result["is_heterogeneous"] is True
    assert result["output_file"] == str(output.resolve())
