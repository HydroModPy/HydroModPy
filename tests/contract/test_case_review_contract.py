"""Contract tests for the ``cases/review_cases.py`` visual-review launchers.

Three spatial packages ship the same registry API (``CaseReviewSpec``,
``available_case_review_names``, ``resolve_case_review_specs``,
``list_case_reviews``, ``run_case_reviews``). This file is the single place the
shared contract is asserted, so a new package re-runs the suite by adding one row
to ``REVIEW_MODULES``. Selection follows registry order rather than request
order, an unknown case is refused by name with the available ones listed, and a
blank request means the whole registry.
"""

from __future__ import annotations

import dataclasses
import importlib
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# Import path -> fragment of the "unknown case" error message.
REVIEW_MODULES: dict[str, str] = {
    "hydromodpy.spatial.domain.cases.review_cases": "Unknown domain/cases review case",
    "hydromodpy.spatial.field.cases.review_cases": "Unknown field/cases review case",
    "hydromodpy.spatial.geographic.cases.review_cases": "Unknown geographic review case",
}

# Packages whose run_case_reviews() calls spec.runner() and needs no input data.
# domain/cases runs a full TOML case from disk, so it is out of scope here.
RUNNER_MODULES: tuple[str, ...] = (
    "hydromodpy.spatial.field.cases.review_cases",
    "hydromodpy.spatial.geographic.cases.review_cases",
)


def _ids(paths) -> list[str]:
    return [path.split(".")[2] for path in paths]


@pytest.fixture(params=list(REVIEW_MODULES), ids=_ids(REVIEW_MODULES))
def review_module(request: pytest.FixtureRequest) -> ModuleType:
    return importlib.import_module(request.param)


@pytest.fixture(params=RUNNER_MODULES, ids=_ids(RUNNER_MODULES))
def runner_module(request: pytest.FixtureRequest) -> ModuleType:
    """A review launcher whose cases run from an in-process runner."""
    return importlib.import_module(request.param)


def _patch_registry(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the registry with three fake cases in b, a, c order; return the runner calls."""
    calls: list[str] = []
    extras = [field.name for field in dataclasses.fields(module.CaseReviewSpec)][2:]

    def spec(name: str) -> Any:
        values = {
            extra: (lambda name=name: calls.append(name) or {"name": name})
            if extra == "runner"
            else Path(f"{name}_config.toml")
            for extra in extras
        }
        return module.CaseReviewSpec(name=name, description=f"Case {name}.", **values)

    monkeypatch.setattr(
        module, "CASE_REVIEW_SPECS", tuple(map(spec, ("case_b", "case_a", "case_c")))
    )
    return calls


def test_module_exposes_the_review_api(review_module: ModuleType) -> None:
    """Five public symbols, a frozen spec led by name and description, a non-empty registry."""
    assert dataclasses.is_dataclass(review_module.CaseReviewSpec)
    assert isinstance(review_module.CASE_REVIEW_SPECS, tuple)
    for symbol in (
        "available_case_review_names",
        "resolve_case_review_specs",
        "list_case_reviews",
        "run_case_reviews",
    ):
        assert callable(getattr(review_module, symbol))
    fields = [field.name for field in dataclasses.fields(review_module.CaseReviewSpec)]
    assert fields[:2] == ["name", "description"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        review_module.CASE_REVIEW_SPECS[0].name = "mutated"
    # A launcher with no case is a packaging failure, not a valid state.
    assert review_module.CASE_REVIEW_SPECS
    names = review_module.available_case_review_names()
    assert names == tuple(spec.name for spec in review_module.CASE_REVIEW_SPECS)


def test_an_unknown_case_is_refused_by_name_with_the_available_cases(
    review_module: ModuleType,
) -> None:
    with pytest.raises(ValueError, match="unknown_case") as excinfo:
        review_module.resolve_case_review_specs(["unknown_case"])
    message = str(excinfo.value)
    assert REVIEW_MODULES[review_module.__name__] in message
    for name in review_module.available_case_review_names():
        assert name in message


@pytest.mark.parametrize(
    ("request_names", "expected"),
    [
        # An empty request means "every case", never "no case".
        pytest.param(None, ["case_b", "case_a", "case_c"], id="none"),
        pytest.param([], ["case_b", "case_a", "case_c"], id="empty-list"),
        pytest.param((), ["case_b", "case_a", "case_c"], id="empty-tuple"),
        pytest.param(["case_c", "case_a"], ["case_a", "case_c"], id="registry_order_not_request_order"),
        pytest.param(["  case_a  ", "case_a", "", "   "], ["case_a"], id="stripped_deduplicated_no_blank"),
        # One bad name fails the whole request instead of running a partial set.
        pytest.param(["case_a", "unknown_case"], None, id="one_unknown"),
    ],
)  # fmt: skip
def test_resolve_filters_the_registry(
    review_module: ModuleType, monkeypatch: pytest.MonkeyPatch, request_names, expected
) -> None:
    _patch_registry(review_module, monkeypatch)
    if not request_names:
        assert (
            review_module.resolve_case_review_specs(request_names)
            == review_module.CASE_REVIEW_SPECS
        )
    if expected is None:
        with pytest.raises(ValueError, match="unknown_case"):
            review_module.resolve_case_review_specs(request_names)
        return
    selected = review_module.resolve_case_review_specs(request_names)
    assert [spec.name for spec in selected] == expected


def test_list_case_reviews_prints_one_line_per_case(
    review_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_registry(review_module, monkeypatch)
    lines: list[str] = []
    review_module.list_case_reviews(printer=lines.append)
    assert lines == ["case_b: Case case_b.", "case_a: Case case_a.", "case_c: Case case_c."]


def test_run_case_reviews_runs_selected_cases_in_registry_order_and_reports_them(
    runner_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each case is announced, warned about the blocking figure, run, then confirmed."""
    calls = _patch_registry(runner_module, monkeypatch)
    messages: list[str] = []
    selected = runner_module.run_case_reviews(["case_c", "case_a"], printer=messages.append)
    assert [spec.name for spec in selected] == ["case_a", "case_c"]
    assert calls == ["case_a", "case_c"]
    assert any("Close the figure window(s)" in message for message in messages)
    assert "[1/2] Running case_a" in messages
    assert "[1/2] Completed case_a" in messages
    assert "[2/2] Running case_c" in messages
    assert "[2/2] Completed case_c" in messages


CASE_TOMLS = sorted(
    Path(__file__).resolve().parents[2].joinpath("hydromodpy", "spatial").glob("**/cases/**/*.toml")
)


def _path_values(node: object) -> list[str]:
    """Every string under a key that ends with ``path``, at any depth."""
    if isinstance(node, dict):
        found = []
        for key, value in node.items():
            if isinstance(value, str) and key.endswith("path"):
                found.append(value)
            else:
                found.extend(_path_values(value))
        return found
    if isinstance(node, list):
        return [value for item in node for value in _path_values(item)]
    return []


@pytest.mark.parametrize("toml_path", CASE_TOMLS, ids=lambda path: path.name)
def test_every_path_of_a_case_toml_resolves_from_its_folder(toml_path: Path) -> None:
    paths = _path_values(tomllib.loads(toml_path.read_text(encoding="utf-8")))
    missing = [value for value in paths if not (toml_path.parent / value).resolve().exists()]
    assert not missing, f"{toml_path.name} names paths that do not exist: {missing}"
