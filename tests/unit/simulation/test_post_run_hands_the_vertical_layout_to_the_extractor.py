"""The extractor stores how the layers were built, as ``[domain.layers]`` says it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.budget_terms import BudgetKeep
from hydromodpy.core.state.run_state import RunState
from hydromodpy.core.vertical_column import (
    VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    VERTICAL_LAYOUT_SURFACES,
)
from hydromodpy.simulation.extraction.post_run import extract_run_outputs
from hydromodpy.simulation.planning.plan import ProcessRun, RunContext, SimulationPlan
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.solver.modflow_nwt.nwt import ModflowConfig
from hydromodpy.spatial.domain.domain_config import DomainConfig


class _RecordingExtractor:
    """Extractor that reads the vertical layout, recording what it got."""

    def __init__(self) -> None:
        self.seen: dict[str, Any] = {}

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
        *,
        vertical_layout: str = VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    ) -> None:
        del sim_id, solver_output_dir, store
        self.seen = {"vertical_layout": vertical_layout}


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


def _context(tmp_path: Path, domain: DomainConfig) -> RunContext:
    run = ProcessRun(
        id="flow_main::modflow6", process_id="flow_main", process_type="flow", solver="modflow6"
    )
    state = RunState(
        cfg=SimpleNamespace(modflownwt=ModflowConfig(), domain=domain),
        setup=SimpleNamespace(time_grid=None),
    )
    plan = SimulationPlan(name="demo", description="demo", runs=(run,))
    return RunContext(plan=plan, run=run, state=state, output_dir=tmp_path)


@pytest.mark.parametrize(
    ("layers", "layout"),
    [
        ({"genmtd_lay": "constant", "nlay": 2}, VERTICAL_LAYOUT_COLUMN_FRACTIONS),
        (
            {"genmtd_lay": "surfaces", "layer": [{"name": "a", "depth": 5.0}, {"name": "b"}]},
            VERTICAL_LAYOUT_SURFACES,
        ),
    ],
)
def test_the_layering_of_the_run_reaches_the_extractor(
    tmp_path: Path, recording: _RecordingExtractor, layers: dict, layout: str
) -> None:
    extract_run_outputs(
        ctx=_context(tmp_path, DomainConfig.model_validate({"layers": layers})),
        sim_id="sim",
        results_config=ResultsConfig(),
        store=object(),
        budget_terms=BudgetKeep.everything(),
    )

    assert recording.seen == {"vertical_layout": layout}
