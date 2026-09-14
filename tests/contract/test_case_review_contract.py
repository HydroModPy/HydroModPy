"""Contract tests for the ``cases/review_cases.py`` visual-review launchers.

Four spatial packages ship the same registry API (``CaseReviewSpec``,
``available_case_review_names``, ``resolve_case_review_specs``,
``list_case_reviews``, ``run_case_reviews``). The behaviour was only ever
tested for ``field`` and ``gmsh_grid``, as two near-identical copies, and
``domain`` had no test at all. This file is the single place the shared
contract is asserted, so a new package re-runs the suite by adding one row
to ``REVIEW_MODULES``.

Guards the selection rules that a copy-paste launcher gets wrong: selection
follows registry order rather than request order, an unknown case is refused
with a message naming both the unknown case and the available ones, and
blank requests fall back to the whole registry instead of an empty run.
"""

from __future__ import annotations

import dataclasses
import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# (import path, fragment of the "unknown case" error message).
REVIEW_MODULES: tuple[tuple[str, str], ...] = (
    ("hydromodpy.spatial.domain.cases.review_cases", "Unknown domain/cases review case"),
    ("hydromodpy.spatial.field.cases.review_cases", "Unknown field/cases review case"),
    ("hydromodpy.spatial.geographic.cases.review_cases", "Unknown geographic review case"),
    ("hydromodpy.spatial.mesh.gmsh_grid.cases.review_cases", "Unknown gmsh_grid review case"),
)

# Packages whose run_case_reviews() calls spec.runner() and needs no input data.
# domain/cases runs a full TOML case from disk, so it is out of scope here.
RUNNER_MODULES: tuple[str, ...] = (
    "hydromodpy.spatial.field.cases.review_cases",
    "hydromodpy.spatial.geographic.cases.review_cases",
    "hydromodpy.spatial.mesh.gmsh_grid.cases.review_cases",
)

MODULE_IDS = [path.split(".")[2] for path, _ in REVIEW_MODULES]
RUNNER_IDS = [path.split(".")[2] for path in RUNNER_MODULES]


@pytest.fixture(params=REVIEW_MODULES, ids=MODULE_IDS)
def review_module(request: pytest.FixtureRequest) -> ModuleType:
    """Import one review launcher and expose it to the shared contract."""
    module_path, _ = request.param
    return importlib.import_module(module_path)


@pytest.fixture(params=REVIEW_MODULES, ids=MODULE_IDS)
def review_module_and_label(request: pytest.FixtureRequest) -> tuple[ModuleType, str]:
    """Import one review launcher together with its error-message label."""
    module_path, label = request.param
    return importlib.import_module(module_path), label


@pytest.fixture(params=RUNNER_MODULES, ids=RUNNER_IDS)
def runner_module(request: pytest.FixtureRequest) -> ModuleType:
    """Import one review launcher whose cases run from an in-process runner."""
    return importlib.import_module(request.param)


def _make_spec(module: ModuleType, name: str, calls: list[str]) -> Any:
    """Build a fake spec for ``module``, recording runner calls in ``calls``."""
    field_names = [field.name for field in dataclasses.fields(module.CaseReviewSpec)]
    extras: dict[str, Any] = {}
    for extra in field_names[2:]:
        if extra == "runner":
            extras[extra] = lambda name=name: calls.append(name) or {"name": name}
        else:
            extras[extra] = Path(f"{name}_config.toml")
    return module.CaseReviewSpec(name=name, description=f"Case {name}.", **extras)


def _patch_registry(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
) -> None:
    """Replace the module registry with three fake cases in b, a, c order."""
    monkeypatch.setattr(
        module,
        "CASE_REVIEW_SPECS",
        tuple(_make_spec(module, name, calls) for name in ("case_b", "case_a", "case_c")),
    )


def test_module_exposes_the_review_api(review_module: ModuleType) -> None:
    """Every launcher exposes the same five public symbols."""
    assert dataclasses.is_dataclass(review_module.CaseReviewSpec)
    assert isinstance(review_module.CASE_REVIEW_SPECS, tuple)
    for symbol in (
        "available_case_review_names",
        "resolve_case_review_specs",
        "list_case_reviews",
        "run_case_reviews",
    ):
        assert callable(getattr(review_module, symbol))


def test_case_review_spec_is_frozen_with_name_and_description(
    review_module: ModuleType,
) -> None:
    """The first two spec fields are name and description, and specs are frozen."""
    fields = [field.name for field in dataclasses.fields(review_module.CaseReviewSpec)]
    assert fields[:2] == ["name", "description"]
    spec = review_module.CASE_REVIEW_SPECS[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "mutated"


def test_registry_is_not_empty(review_module: ModuleType) -> None:
    """A launcher with no case is a packaging failure, not a valid state."""
    assert review_module.CASE_REVIEW_SPECS


def test_available_names_follow_registry_order(review_module: ModuleType) -> None:
    """available_case_review_names mirrors the registry, order included."""
    names = review_module.available_case_review_names()
    assert names == tuple(spec.name for spec in review_module.CASE_REVIEW_SPECS)


@pytest.mark.parametrize("case_names", [None, [], ()], ids=["none", "empty-list", "empty-tuple"])
def test_resolve_without_names_returns_the_whole_registry(
    review_module: ModuleType,
    case_names: Any,
) -> None:
    """An empty request means "every case", never "no case"."""
    assert review_module.resolve_case_review_specs(case_names) == review_module.CASE_REVIEW_SPECS


def test_resolve_returns_registry_order_not_request_order(
    review_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selection is filtered from the registry, so request order is ignored."""
    calls: list[str] = []
    _patch_registry(review_module, monkeypatch, calls)

    selected = review_module.resolve_case_review_specs(["case_c", "case_a"])

    assert [spec.name for spec in selected] == ["case_a", "case_c"]


def test_resolve_deduplicates_and_ignores_blank_names(
    review_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Names are stripped, blanks dropped and duplicates collapsed."""
    calls: list[str] = []
    _patch_registry(review_module, monkeypatch, calls)

    selected = review_module.resolve_case_review_specs(["  case_a  ", "case_a", "", "   "])

    assert [spec.name for spec in selected] == ["case_a"]


def test_resolve_rejects_an_unknown_case(
    review_module_and_label: tuple[ModuleType, str],
) -> None:
    """An unknown case is refused, and the message names it."""
    module, label = review_module_and_label
    with pytest.raises(ValueError, match="unknown_case") as excinfo:
        module.resolve_case_review_specs(["unknown_case"])
    assert label in str(excinfo.value)


def test_unknown_case_error_lists_the_available_cases(
    review_module: ModuleType,
) -> None:
    """The refusal is actionable: it lists what the caller could have asked for."""
    with pytest.raises(ValueError) as excinfo:
        review_module.resolve_case_review_specs(["unknown_case"])
    message = str(excinfo.value)
    for name in review_module.available_case_review_names():
        assert name in message


def test_resolve_rejects_an_unknown_case_mixed_with_a_valid_one(
    review_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One bad name fails the whole request instead of running a partial set."""
    calls: list[str] = []
    _patch_registry(review_module, monkeypatch, calls)

    with pytest.raises(ValueError, match="unknown_case"):
        review_module.resolve_case_review_specs(["case_a", "unknown_case"])


def test_list_case_reviews_prints_one_line_per_case(
    review_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list_case_reviews writes "name: description" through the injected printer."""
    calls: list[str] = []
    _patch_registry(review_module, monkeypatch, calls)
    lines: list[str] = []

    review_module.list_case_reviews(printer=lines.append)

    assert lines == ["case_b: Case case_b.", "case_a: Case case_a.", "case_c: Case case_c."]


def test_run_case_reviews_runs_selected_cases_in_registry_order(
    runner_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runners fire in registry order, and the launcher returns what it ran."""
    calls: list[str] = []
    _patch_registry(runner_module, monkeypatch, calls)
    messages: list[str] = []

    selected = runner_module.run_case_reviews(["case_c", "case_a"], printer=messages.append)

    assert [spec.name for spec in selected] == ["case_a", "case_c"]
    assert calls == ["case_a", "case_c"]


def test_run_case_reviews_warns_about_the_blocking_figure_window(
    runner_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator is told the run blocks until the figure is closed."""
    calls: list[str] = []
    _patch_registry(runner_module, monkeypatch, calls)
    messages: list[str] = []

    runner_module.run_case_reviews(["case_a"], printer=messages.append)

    assert any("Close the figure window(s)" in message for message in messages)


def test_run_case_reviews_reports_progress_for_each_case(
    runner_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each case is announced then confirmed with an index over the total."""
    calls: list[str] = []
    _patch_registry(runner_module, monkeypatch, calls)
    messages: list[str] = []

    runner_module.run_case_reviews(["case_a", "case_c"], printer=messages.append)

    assert "[1/2] Running case_a" in messages
    assert "[1/2] Completed case_a" in messages
    assert "[2/2] Running case_c" in messages
    assert "[2/2] Completed case_c" in messages
