"""Workspace.score and Workspace.score_network stack the projects with a project column."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.project.accessors import Workspace


class Runs:
    def __init__(self, value):
        self.value = value

    def _table(self, *args, **kwargs):
        if self.value is None:
            raise NothingThereError("No run of the set has a series to score.")
        return pd.DataFrame({"sim_id": ["a"], "value": [self.value], "args": [(args, kwargs)]})

    score = score_network = _table


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / "projects").mkdir()
    monkeypatch.setattr(Workspace, "projects", ["p1", "p2", "empty"])
    held = {"p1": 1.0, "p2": 2.0, "empty": None}
    monkeypatch.setattr(
        Workspace, "__getitem__", lambda self, name: SimpleNamespace(runs=lambda: Runs(held[name]))
    )
    return Workspace(tmp_path)


def test_the_projects_are_stacked_with_the_project_first(workspace):
    table = workspace.score({"w": (None, None)}, metrics=["nse"])
    assert list(table.columns)[0] == "project"
    assert dict(zip(table["project"], table["value"], strict=True)) == {"p1": 1.0, "p2": 2.0}
    assert table["args"].iloc[0] == (({"w": (None, None)},), {"metrics": ["nse"]})


def test_the_network_score_is_stacked_the_same_way(workspace):
    assert set(workspace.score_network(window=("2001-01-01", "2002-01-01"))["project"]) == {
        "p1",
        "p2",
    }


def test_a_workspace_with_nothing_to_score_is_refused(tmp_path, monkeypatch):
    (tmp_path / "projects").mkdir()
    monkeypatch.setattr(Workspace, "projects", ["p"])
    monkeypatch.setattr(Workspace, "__getitem__", lambda self, name: SimpleNamespace(runs=lambda: Runs(None)))  # fmt: skip
    with pytest.raises(NothingThereError, match="has runs to score"):
        Workspace(tmp_path).score()
