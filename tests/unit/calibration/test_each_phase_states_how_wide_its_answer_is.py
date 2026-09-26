"""Each phase states how wide its answer is, with a default that follows what it scores.

A phase may write its own ``uncertainty``, with the keys of
``[calibration.uncertainty]``, which stays the default of every phase. Key by
key, the phase wins, then the section, then a default read off what the phase
scores: one mesh cell, in metres, for a phase scored only by network distances,
and five per cent of the best cost for any other. The cell is the median
distance between the centres of neighbouring cells, measured by the network
criterion on the mesh it scores.

No solver runs. The widths are read off the configuration, the check off
preflight, and the one search goes through an evaluator that returns a gap in
metres and the cell it was measured on, the way the network criterion does.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.observations.network_geometry import cell_spacing_m
from hydromodpy.calibration.optim.tolerance import FIVE_PER_CENT, ONE_MESH_CELL
from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.calibration.runners.cli_runner import load_toml_calibration, run_calibration_cli
from hydromodpy.calibration.runners.staged_runner import _phase_config, phase_summaries
from hydromodpy.calibration.runners.state import build_cache_context, space_from_config
from hydromodpy.config import HydroModPyConfig

pytestmark = pytest.mark.fast

SECTION = """
[calibration]
max_iter = 5

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.005, 0.35]
transform = "log"
target = "flow.param.Sy.field.value"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "streams.gpkg"

[calibration.outputs.q]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observed_values = [1.0, 2.0, 3.0]

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["q"]
"""

PHASES = """
[[calibration.phases]]
name = "k_network"
parameters = ["K"]
objective_blocks = ["network"]
{k_extra}

[[calibration.phases]]
name = "sy_hydrograph"
parameters = ["Sy"]
objective_blocks = {{ hydrograph = 99, network = 1 }}
depends_on = "k_network"
{sy_extra}
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _config(tmp_path: Path, *, section: str = "", k_extra: str = "", sy_extra: str = ""):
    text = SECTION + section + PHASES.format(k_extra=k_extra, sy_extra=sy_extra)
    cfg, _raw = load_toml_calibration(_write(tmp_path, text))
    return cfg


def _widths(cfg: CalibrationConfig) -> dict[str, dict]:
    return {row["name"]: row["interval_width"] for row in phase_summaries(cfg)}


# -- the cell ----------------------------------------------------------------


def _rectangles(nrow: int, ncol: int, dx: float, dy: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (centres, face_node_connectivity) of a grid of dx by dy cells."""
    nodes_per_row = ncol + 1
    corner = (np.arange(nrow)[:, None] * nodes_per_row + np.arange(ncol)[None, :]).reshape(-1)
    connectivity = np.column_stack(
        [corner, corner + 1, corner + nodes_per_row + 1, corner + nodes_per_row]
    )
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    centres = np.column_stack([(cols + 0.5) * dx, (rows + 0.5) * dy])
    return centres, connectivity


def test_one_cell_is_the_median_distance_between_neighbouring_centres() -> None:
    # Two rows of three cells, 40 m wide and 60 m tall: four pairs side by side
    # at 40 m, three pairs one above the other at 60 m. Diagonals share no edge.
    centres, connectivity = _rectangles(2, 3, dx=40.0, dy=60.0)

    assert cell_spacing_m(centres, connectivity) == pytest.approx(40.0)


def test_the_cell_is_measured_where_the_criterion_scores() -> None:
    # Only the left column is kept: its one pair is stacked, 60 m apart.
    centres, connectivity = _rectangles(2, 3, dx=40.0, dy=60.0)
    within = np.array([True, False, False, True, False, False])

    assert cell_spacing_m(centres, connectivity, within=within) == pytest.approx(60.0)


# -- the default follows what the phase scores ------------------------------


def test_a_phase_scored_on_network_distances_takes_one_mesh_cell(tmp_path) -> None:
    width = _widths(_config(tmp_path))["k_network"]

    assert width["tolerance"] is None
    assert (width["mode"], width["source"], width["rule"]) == ("absolute", "default", ONE_MESH_CELL)
    assert width["on_distances"] is True


def test_a_phase_scored_on_a_hydrograph_takes_five_per_cent(tmp_path) -> None:
    # The hydrograph block is not a distance, so the share of the network block
    # does not make this phase one scored on distances.
    width = _widths(_config(tmp_path))["sy_hydrograph"]

    assert (width["tolerance"], width["mode"]) == (0.05, "relative")
    assert (width["source"], width["rule"]) == ("default", FIVE_PER_CENT)


def test_a_transformed_distance_is_no_longer_in_metres(tmp_path) -> None:
    text = SECTION.replace(
        'metric = "distance_gap"\nuses_outputs = ["net"]',
        'metric = "distance_gap"\nuses_outputs = ["net"]\ntransform = "log"',
    ) + PHASES.format(k_extra="", sy_extra="")
    cfg, _raw = load_toml_calibration(_write(tmp_path, text))

    width = _widths(cfg)["k_network"]

    assert (width["tolerance"], width["mode"], width["on_distances"]) == (0.05, "relative", False)


def test_the_section_still_applies_to_a_phase_that_writes_none(tmp_path) -> None:
    cfg = _config(
        tmp_path, section='\n[calibration.uncertainty]\nmode = "absolute"\ntolerance = 150.0\n'
    )
    widths = _widths(cfg)

    for name in ("k_network", "sy_hydrograph"):
        assert (widths[name]["tolerance"], widths[name]["mode"]) == (150.0, "absolute")
        assert widths[name]["source"] == "section"


def test_a_value_written_in_the_phase_wins_over_the_section_and_the_default(tmp_path) -> None:
    cfg = _config(
        tmp_path,
        section='\n[calibration.uncertainty]\nmode = "absolute"\ntolerance = 150.0\n',
        k_extra="uncertainty = { tolerance = 225.0 }",
        sy_extra='uncertainty = { mode = "relative", tolerance = 0.1 }',
    )
    widths = _widths(cfg)

    assert (widths["k_network"]["tolerance"], widths["k_network"]["source"]) == (225.0, "phase")
    # The mode the phase did not write is the section's.
    assert widths["k_network"]["mode_source"] == "section"
    assert (widths["sy_hydrograph"]["tolerance"], widths["sy_hydrograph"]["mode"]) == (
        0.1,
        "relative",
    )
    assert widths["sy_hydrograph"]["source"] == "phase"
    # The phase runs under its own keys, the section's filling the others.
    k_phase = next(decl for decl in cfg.phases if decl.name == "k_network")
    assert _phase_config(cfg, k_phase).uncertainty.tolerance == 225.0
    assert _phase_config(cfg, k_phase).uncertainty.mode == "absolute"


def test_a_phase_that_names_another_method_leaves_the_section_restarts(tmp_path) -> None:
    cfg = _config(
        tmp_path,
        section='\n[calibration.uncertainty]\nmethod = "multistart"\nrestarts = 4\n',
        k_extra='uncertainty = { method = "cost_profile" }',
    )
    k_phase, sy_phase = cfg.phases

    assert cfg.uncertainty_for(k_phase).method == "cost_profile"
    assert cfg.uncertainty_for(k_phase).restarts is None
    assert cfg.uncertainty_for(sy_phase).restarts == 4


def test_a_phase_uncertainty_that_does_not_hold_over_the_section_is_refused(tmp_path) -> None:
    with pytest.raises(Exception, match="phase 'k_network' writes an uncertainty"):
        _config(tmp_path, k_extra='uncertainty = { method = "multistart" }')


def test_a_phase_is_answered_about_a_posterior_like_the_section() -> None:
    with pytest.raises(ValidationError, match="'posterior' is not offered"):
        CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-7, 1e-3]}},
                "phases": [
                    {"name": "p", "parameters": ["K"], "uncertainty": {"method": "posterior"}}
                ],
            }
        )


def test_the_width_does_not_enter_the_params_hash(tmp_path) -> None:
    # The width is read off the trials after the search and changes no cost, so
    # a new width re-solves nothing.
    plain = _config(tmp_path)
    widened = plain.model_copy(
        update={"uncertainty": plain.uncertainty.model_copy(update={"tolerance": 300.0})}
    )

    def context(cfg: CalibrationConfig) -> dict:
        return build_cache_context(
            cfg=cfg,
            trial_ctx=None,
            space=space_from_config(cfg),
            override_paths={},
            objective_entrypoint=None,
        )

    assert context(plain) == context(widened)


# -- --check -----------------------------------------------------------------

PROJECT = """
[workspace]
project_root = "{root}"

[workflow]
mode = "calibration"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"

[geographic]
source_mode = "synthetic"

[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5

[flow.param.Sy.field]
id = "Sy"
kind = "homogeneous"
unit = "-"
value = 0.05
"""


def _check(tmp_path: Path, *, section: str = "", k_extra: str = "") -> list:
    (tmp_path / "streams.gpkg").write_bytes(b"")
    text = (
        PROJECT.format(root=tmp_path)
        + SECTION
        + section
        + PHASES.format(k_extra=k_extra, sy_extra="")
    )
    path = _write(tmp_path, text)
    return preflight_calibration(HydroModPyConfig.from_toml(path), source=path)


def _width_findings(findings: list) -> list:
    return [item for item in findings if "fraction of a distance" in item.detail]


def test_check_passes_the_defaults(tmp_path) -> None:
    assert _width_findings(_check(tmp_path)) == []


def test_check_refuses_a_relative_width_written_in_a_network_phase(tmp_path) -> None:
    findings = _width_findings(_check(tmp_path, k_extra='uncertainty = { mode = "relative" }'))

    assert [(item.severity, item.where) for item in findings] == [
        ("error", "[[calibration.phases]] 'k_network'")
    ]
    assert "written in this phase" in findings[0].detail


def test_check_refuses_a_relative_width_the_section_hands_a_network_phase(tmp_path) -> None:
    # The hydrograph phase takes the same relative width and is not named.
    findings = _width_findings(
        _check(tmp_path, section='\n[calibration.uncertainty]\nmode = "relative"\n')
    )

    assert [item.where for item in findings] == ["[[calibration.phases]] 'k_network'"]
    assert "written in [calibration.uncertainty]" in findings[0].detail


# -- the single-metric route scores a distance too ---------------------------

SINGLE_METRIC_SECTION = """
[calibration]
objective = "distance_gap"
{uncertainty}

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
"""

SINGLE_METRIC_PHASE = """
[calibration]

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"

[[calibration.phases]]
name = "k_gap"
parameters = ["K"]
objective = "distance_gap"
{uncertainty}
"""


@pytest.mark.parametrize(
    ("template", "phase"),
    [(SINGLE_METRIC_SECTION, False), (SINGLE_METRIC_PHASE, True)],
    ids=["section", "phase"],
)
def test_a_single_metric_distance_takes_one_mesh_cell(tmp_path, template, phase) -> None:
    cfg, _raw = load_toml_calibration(_write(tmp_path, template.format(uncertainty="")))

    width = cfg.interval_width_for(cfg.phases[0] if phase else None)

    assert (width.tolerance, width.mode, width.rule) == (None, "absolute", ONE_MESH_CELL)


@pytest.mark.parametrize(
    ("template", "uncertainty", "where"),
    [
        (
            SINGLE_METRIC_SECTION,
            '\n[calibration.uncertainty]\nmode = "relative"\n',
            "[calibration.uncertainty]",
        ),
        (
            SINGLE_METRIC_PHASE,
            'uncertainty = { mode = "relative" }',
            "[[calibration.phases]] 'k_gap'",
        ),
    ],
    ids=["section", "phase"],
)
def test_check_refuses_a_relative_width_on_a_single_metric_distance(
    tmp_path, template, uncertainty, where
) -> None:
    path = _write(
        tmp_path, PROJECT.format(root=tmp_path) + template.format(uncertainty=uncertainty)
    )

    findings = _width_findings(preflight_calibration(HydroModPyConfig.from_toml(path), source=path))

    assert [(item.severity, item.where) for item in findings] == [("error", where)]


def test_list_phases_says_where_the_mode_comes_from_when_the_tolerance_is_default(
    tmp_path, capsys
) -> None:
    import argparse

    from hydromodpy.cli.commands import calibrate as calibrate_cmd

    text = SECTION + '\n[calibration.uncertainty]\nmode = "absolute"\n'
    path = _write(tmp_path, text + PHASES.format(k_extra="", sy_extra=""))
    calibrate_cmd.run(
        argparse.Namespace(config=path, check=False, list_phases=True, phase=None, profile=None)
    )

    k_line, sy_line = capsys.readouterr().out.splitlines()
    assert k_line.split("\t")[4] == (
        "width one mesh cell (default, measured on the mesh when the phase runs; "
        "mode absolute written in [calibration.uncertainty])"
    )
    assert sy_line.split("\t")[4] == (
        "width 0.05 in the unit of the cost (default; "
        "mode absolute written in [calibration.uncertainty])"
    )


# -- the run reads the cell off its trials and reports the width it used ----


class _GapInMetres:
    """A network gap in metres, zero at K = 1e-5, measured on 60 m cells."""

    evaluator_id = "test_gap_in_metres"
    needs_prepared_model = False

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        gap = abs(math.log10(float(request.values["K"])) + 5.0) * 100.0
        return TrialOutcome(
            cost=gap,
            status="completed",
            duration_s=0.0,
            components={"net.cell_spacing_m": 60.0},
        )


@pytest.fixture
def gap_in_metres():
    evaluation_registry.register(_GapInMetres, replace=True)
    try:
        yield _GapInMetres
    finally:
        evaluation_registry.unregister(_GapInMetres.evaluator_id)


SINGLE_SEARCH = """
[calibration]
method = "grid"
max_iter = 9
evaluator = "test_gap_in_metres"
use_cache = false
optimizer_kwargs = {{ points_per_dim = 9 }}
{uncertainty}

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "streams.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


def _run(tmp_path: Path, uncertainty: str = ""):
    path = _write(tmp_path, SINGLE_SEARCH.format(uncertainty=uncertainty))
    return run_calibration_cli(path, workspace=tmp_path, return_report=True)


def test_the_run_reads_one_mesh_cell_off_the_trials(tmp_path, gap_in_metres) -> None:
    report = _run(tmp_path)

    width = report.extra["interval_width"]
    assert (width["tolerance"], width["mode"]) == (60.0, "absolute")
    assert (width["source"], width["rule"]) == ("default", ONE_MESH_CELL)
    (interval,) = report.extra["parameter_intervals"]
    assert interval["threshold"] == pytest.approx(report.best_objective + 60.0)
    assert interval["mode"] == "absolute"


def test_the_run_reports_a_written_width_and_where_it_was_written(tmp_path, gap_in_metres) -> None:
    report = _run(tmp_path, '\n[calibration.uncertainty]\nmode = "absolute"\ntolerance = 120.0\n')

    width = report.extra["interval_width"]
    assert (width["tolerance"], width["source"]) == (120.0, "section")
    (interval,) = report.extra["parameter_intervals"]
    assert interval["threshold"] == pytest.approx(report.best_objective + 120.0)
