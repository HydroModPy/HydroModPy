from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from hydromodpy.field.cases import review_cases
from hydromodpy.field.cases.square import FieldMeshSquare, FieldSquare
from hydromodpy.field.cases.square.run_field_demo import run_field_demo_case
from hydromodpy.field.core.field_param import FieldParam


def test_run_case_reviews_uses_registry_order_for_selected_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    messages: list[str] = []

    def _runner(name: str):
        def _call() -> dict[str, str]:
            calls.append(name)
            return {"name": name}

        return _call

    monkeypatch.setattr(
        review_cases,
        "CASE_REVIEW_SPECS",
        (
            review_cases.CaseReviewSpec("case_b", "Second case.", _runner("case_b")),
            review_cases.CaseReviewSpec(
                "case_a", "First selected case.", _runner("case_a")
            ),
            review_cases.CaseReviewSpec(
                "case_c", "Third selected case.", _runner("case_c")
            ),
        ),
    )

    selected = review_cases.run_case_reviews(
        ["case_c", "case_a"],
        printer=messages.append,
    )

    assert [spec.name for spec in selected] == ["case_a", "case_c"]
    assert calls == ["case_a", "case_c"]
    assert any("Close the figure window(s)" in message for message in messages)


def test_resolve_case_review_specs_rejects_unknown_case() -> None:
    with pytest.raises(ValueError, match="unknown_case"):
        review_cases.resolve_case_review_specs(["unknown_case"])


def test_run_field_demo_case_writes_output_without_show() -> None:
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
