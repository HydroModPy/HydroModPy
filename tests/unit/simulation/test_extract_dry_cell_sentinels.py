"""The configured HDRY / HNOFLO sentinels must reach the output extractor."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.simulation.extraction.post_run import extract_run_outputs
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.solver.modflow_nwt.nwt import ModflowConfig


class _RecordingExtractor:
    """Extractor exposing the MODFLOW-NWT masking contract, recording its call."""

    def __init__(self) -> None:
        self.seen: dict[str, Any] = {}

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
        *,
        hdry: float,
        hnoflo: float,
        model_name: str | None = None,
        budget_spatial_fields: bool = False,
        start_datetime: object | None = None,
    ) -> None:
        del sim_id, solver_output_dir, store, model_name, budget_spatial_fields, start_datetime
        self.seen = {"hdry": hdry, "hnoflo": hnoflo}


def _context(tmp_path: Path, modflownwt: ModflowConfig) -> RunContext:
    run = ProcessRun(
        id="flow_main::modflow_nwt",
        process_id="flow_main",
        process_type="flow",
        solver="modflow_nwt",
    )
    plan = SimulationPlan(name="demo", description="demo", runs=(run,))
    state = SimpleNamespace(
        cfg=SimpleNamespace(modflownwt=modflownwt),
        setup=SimpleNamespace(time_grid=None),
        execution=SimpleNamespace(
            output_dirs_by_run_id={run.id: tmp_path},
            models_by_run_id={},
        ),
    )
    return RunContext(plan=plan, run=run, state=state)


@pytest.fixture
def recording(monkeypatch) -> _RecordingExtractor:
    extractor = _RecordingExtractor()
    monkeypatch.setattr(
        "hydromodpy.simulation.extraction.post_run.get_solver_registry_provider",
        lambda: SimpleNamespace(get_extractor_instance=lambda *_: extractor),
    )
    monkeypatch.setattr(
        "hydromodpy.simulation.extraction.post_run._finalize_run_provenance",
        lambda **_kwargs: None,
    )
    return extractor


def test_configured_sentinels_reach_the_extractor(tmp_path, recording) -> None:
    config = ModflowConfig.model_validate(
        {"runtime": {"upw": {"hdry": -1234.0}, "bas": {"hnoflo": -4321.0}}}
    )

    extract_run_outputs(
        ctx=_context(tmp_path, config),
        sim_id="sim",
        results_config=ResultsConfig(),
        store=object(),
    )

    assert recording.seen == {"hdry": -1234.0, "hnoflo": -4321.0}


def test_default_sentinels_are_the_modflow_nwt_defaults(tmp_path, recording) -> None:
    extract_run_outputs(
        ctx=_context(tmp_path, ModflowConfig()),
        sim_id="sim",
        results_config=ResultsConfig(),
        store=object(),
    )

    assert recording.seen == {"hdry": -100.0, "hnoflo": -9999.0}
