"""Tests for the no-surface-exit diagnosis and the research hint of ``config_flags``."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.budget.terms import budget_terms_for
from hydromodpy.results.derive.config_flags import (
    enable_options_hint,
    no_surface_exit_reason,
)

pytestmark = pytest.mark.unit


class _Group:
    def __init__(self, attrs: dict[str, Any]) -> None:
        self.attrs = attrs


class _Store:
    def __init__(self, budget: _Group | None) -> None:
        self.root = {} if budget is None else {"budget": budget}

    def close(self) -> None:
        pass


class _FakeRun:
    """Duck-typed run: some fields present, a catalog that opens a store or none."""

    def __init__(
        self,
        present: set[tuple[str, str | None]],
        *,
        budget: _Group | None = None,
        with_catalog: bool = True,
        raises: Exception | None = None,
    ) -> None:
        self._present = present
        self._raises = raises
        self.sim_id = "sim"
        if with_catalog:
            self._catalog = SimpleNamespace(open_zarr=lambda _sim_id: _Store(budget))

    def has_field(self, name: str, subgroup: str | None = None) -> bool:
        if self._raises is not None:
            raise self._raises
        return (name, subgroup) in self._present


def _declared(policy: str, terms: tuple[str, ...] = ()) -> _Group:
    return _Group({"policy": policy, "kept_terms": list(terms)})


_NO_EXIT_RELEASE = (
    "the model has no drain, stream, lake or surface excess, so no groundwater "
    "leaves the aquifer that way and the run has no release_flux"
)
_NO_EXIT_DRAIN = (
    "the model has no drain, so no groundwater leaves the aquifer that way "
    "and the run has no outflow_drain"
)


def test_research_hint_names_replay() -> None:
    """A kept calibration trial is told to replay, not to set an option."""
    hint = enable_options_hint(["keep_per_cell_budget"], level="research")
    assert "hmp replay <run>" in hint
    assert "keep_per_cell_budget" not in hint


@pytest.mark.parametrize(
    ("fields", "expected"),
    [([], None), (["head", "recharge"], None)],
)
def test_reason_ignores_fields_that_are_not_exits(fields: list[str], expected: None) -> None:
    run = _FakeRun(set())
    assert no_surface_exit_reason(run, fields) is expected


def test_reason_is_none_without_has_field() -> None:
    assert no_surface_exit_reason(object(), ["release_flux"]) is None


def test_reason_is_none_when_the_field_exists() -> None:
    run = _FakeRun({("release_flux", None)})
    assert no_surface_exit_reason(run, ["release_flux"]) is None


def test_reason_is_none_when_an_exit_term_has_an_array() -> None:
    run = _FakeRun({("drain", "budget")})
    assert no_surface_exit_reason(run, ["outflow_drain"]) is None


@pytest.mark.parametrize(
    ("field", "expected"),
    [("release_flux", _NO_EXIT_RELEASE), ("outflow_drain", _NO_EXIT_DRAIN)],
)
def test_reason_for_a_store_that_declares_all_with_a_budget_term(field: str, expected: str) -> None:
    run = _FakeRun({("recharge", "budget")}, budget=_declared("all"))
    assert no_surface_exit_reason(run, [field]) == expected


def test_reason_for_an_undeclared_store_with_a_budget_term() -> None:
    run = _FakeRun({("recharge", "budget")}, budget=None)
    assert no_surface_exit_reason(run, ["release_flux"]) == _NO_EXIT_RELEASE


def test_reason_is_none_when_all_is_declared_without_any_term() -> None:
    run = _FakeRun(set(), budget=_declared("all"))
    assert no_surface_exit_reason(run, ["release_flux"]) is None


def test_reason_is_none_for_a_stand_in_without_catalog_and_no_term() -> None:
    run = _FakeRun(set(), with_catalog=False)
    assert no_surface_exit_reason(run, ["outflow_drain"]) is None


def test_reason_when_consumers_policy_kept_every_exit_term() -> None:
    run = _FakeRun(set(), budget=_declared("consumers", budget_terms_for("outflow_drain")))
    assert no_surface_exit_reason(run, ["outflow_drain"]) == _NO_EXIT_DRAIN


def test_reason_is_none_when_consumers_policy_kept_other_terms_only() -> None:
    run = _FakeRun(set(), budget=_declared("consumers", ("recharge",)))
    assert no_surface_exit_reason(run, ["outflow_drain"]) is None


@pytest.mark.parametrize("error", [TypeError("x"), RuntimeError("x"), KeyError("x"), OSError("x")])
def test_reason_is_none_when_the_store_read_fails(error: Exception) -> None:
    run = _FakeRun(set(), raises=error)
    assert no_surface_exit_reason(run, ["release_flux"]) is None
