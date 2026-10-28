"""The field demo runner, :mod:`hydromodpy.spatial.field.cases.square.run_field_demo`.

The registry API it shares with the other ``cases/review_cases.py`` modules
is asserted once in ``tests/contract/test_case_review_contract.py``.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.field.cases.square import FieldMeshSquare
from hydromodpy.spatial.field.cases.square.run_field_demo import run_field_demo_case
from hydromodpy.spatial.field.core.field_param import FieldParam
from tests._helpers.field_cases import two_zone_square


def test_run_field_demo_case_writes_output_without_show(tmp_path: Path) -> None:
    """The demo case must write its figure even with show_plot disabled."""
    field_param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 10.0, "micaschists": 2.0},
        field_spatial_id="field_square",
    )
    mesh = FieldMeshSquare.from_dict({"kind": "structured", "target_n_cells": 100})
    output_path = tmp_path / "field_case_demo.png"

    result = run_field_demo_case(
        field_param=field_param,
        mesh=mesh,
        field=two_zone_square(),
        output_file=output_path,
        show_plot=False,
    )

    assert output_path.exists()
    assert result["mesh_kind"] == "structured"
    assert result["n_cells"] == mesh.n_cells
    assert result["is_heterogeneous"] is True
    assert result["output_file"] == str(output_path.resolve())
