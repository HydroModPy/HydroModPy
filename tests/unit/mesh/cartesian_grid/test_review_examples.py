from __future__ import annotations

import pytest

from hydromodpy.spatial.mesh.cartesian_grid.examples import review_examples


def test_run_example_reviews_uses_registry_order_for_selected_examples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    messages: list[str] = []

    def _runner(name: str):
        def _call() -> int:
            calls.append(name)
            return 0

        return _call

    monkeypatch.setattr(
        review_examples,
        "EXAMPLE_REVIEW_SPECS",
        (
            review_examples.ExampleReviewSpec("three_d", "Third demo.", _runner("three_d")),
            review_examples.ExampleReviewSpec("two_d", "Second demo.", _runner("two_d")),
            review_examples.ExampleReviewSpec("generation", "First demo.", _runner("generation")),
        ),
    )

    selected = review_examples.run_example_reviews(
        ["generation", "three_d"],
        printer=messages.append,
    )

    assert [spec.name for spec in selected] == ["three_d", "generation"]
    assert calls == ["three_d", "generation"]
    assert any("Close the figure window(s)" in message for message in messages)


def test_resolve_example_review_specs_rejects_unknown_example() -> None:
    with pytest.raises(ValueError, match="unknown_example"):
        review_examples.resolve_example_review_specs(["unknown_example"])
