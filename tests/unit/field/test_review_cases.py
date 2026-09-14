"""Unit tests for the field visual review launcher.

The registry API it shares with the other ``cases/review_cases.py`` modules
is asserted once in ``tests/contract/test_case_review_contract.py``. Only the
field-specific demo runner is tested here.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hydromodpy.spatial.field.cases.square import FieldMeshSquare, FieldSquare
from hydromodpy.spatial.field.cases.square.run_field_demo import run_field_demo_case
from hydromodpy.spatial.field.core.field_param import FieldParam


def test_run_field_demo_case_writes_output_without_show() -> None:
    """The demo case must write its figure even with show_plot disabled."""
    field_param = FieldParam.from_dict(
        {
            "id": "K",
            "kind": "heterogeneous",
            "values": {"granite": 10.0, "micaschists": 2.0},
            "field_spatial_id": "field_square",
        }
    )
    mesh = FieldMeshSquare.from_dict({"kind": "structured", "target_n_cells": 100})
    field = FieldSquare.from_dict(
        {
            "id": "field_square",
            "line": "diag_main",
            "zone1_side": "positive",
            "zone1_name": "granite",
            "zone2_name": "micaschists",
        }
    )
    output_dir = Path("tmp") / "field_case_review_outputs"
    shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve()
    output_path = output_dir / "field_case_demo.png"

    try:
        result = run_field_demo_case(
            field_param=field_param,
            mesh=mesh,
            field=field,
            output_file=output_path,
            show_plot=False,
        )

        assert output_path.exists()
        assert result["mesh_kind"] == "structured"
        assert result["n_cells"] == mesh.n_cells
        assert result["is_heterogeneous"] is True
        assert result["output_file"] == str(output_path.resolve())
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
