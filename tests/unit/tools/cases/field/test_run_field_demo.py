"""The field demo runner, :mod:`tools.cases.field.square.run_field_demo`."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.model.properties.field_param import FieldParam
from hydromodpy.model.properties.field_param_io import field_param_from_toml
from hydromodpy.model.properties.unit_square_mesh import FieldMeshSquare
from tests._helpers.field_cases import two_zone_square
from tools.cases.field.square import run_field_demo
from tools.cases.field.square.run_field_demo import run_field_demo_case


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


def test_the_field_toml_of_the_demo_reads_one_value_per_zone():
    path = Path(run_field_demo.__file__).with_name(run_field_demo.DEFAULT_FIELD_PARAM_CONFIG_FILE)
    param = field_param_from_toml(path)
    assert param.is_heterogeneous
    assert (param.identifier, param.field_spatial_id) == ("K", "field_square")
    assert param.values_by_key == {"granite": 10.0, "micaschists": 2.0}
