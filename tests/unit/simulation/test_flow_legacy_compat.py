"""Unit tests for explicit legacy flow compatibility helpers."""

from __future__ import annotations

import pickle
from types import SimpleNamespace

from hydromodpy.simulation.adapters.flow.legacy_compat import (
    should_write_legacy_pre_run_pickle,
    write_legacy_pre_run_pickle,
)


def test_should_write_legacy_pre_run_pickle_requires_explicit_flag() -> None:
    assert should_write_legacy_pre_run_pickle(None) is False
    assert should_write_legacy_pre_run_pickle({}) is False
    assert should_write_legacy_pre_run_pickle({"write_legacy_pre_run_pickle": False}) is False
    assert should_write_legacy_pre_run_pickle({"write_legacy_pre_run_pickle": True}) is True


def test_write_legacy_pre_run_pickle_writes_historical_payload(tmp_path) -> None:
    workspace = SimpleNamespace(simulations_folder=tmp_path)
    model = SimpleNamespace(name="demo_model")

    write_legacy_pre_run_pickle(workspace, "demo_model", model)

    payload_path = tmp_path / "demo_model" / "results_demo_model.pkl"
    assert payload_path.exists()

    with payload_path.open("rb") as fh:
        payload = pickle.load(fh)

    assert payload["list_model_name"] == ["demo_model"]
    assert payload["list_model_modflow"] == [model]
