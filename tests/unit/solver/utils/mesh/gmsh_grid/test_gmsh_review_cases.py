from __future__ import annotations

import pytest

from hydromodpy.solver.utils.mesh.gmsh_grid.cases import review_cases


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
            review_cases.CaseReviewSpec("case_a", "First selected case.", _runner("case_a")),
            review_cases.CaseReviewSpec("case_c", "Third selected case.", _runner("case_c")),
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
