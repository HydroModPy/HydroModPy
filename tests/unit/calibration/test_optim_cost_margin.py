"""Tests of `optim.cost_margin`."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.optim.cost_margin import (
    DEFAULT_MARGIN,
    FIVE_PER_CENT,
    ONE_MESH_CELL,
    margin_intervals,
    root_interval,
)
from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.calibration.runners.cli_runner import load_toml_calibration, run_calibration_cli
from hydromodpy.calibration.runners.staged_runner import _phase_config, phase_summaries
from hydromodpy.calibration.runners.state import build_cache_context, space_from_config
from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.stream_geometry import neighbour_spacing_m
from hydromodpy.results.session.descriptor import read_session
from tests.unit.calibration._factories_runners import write_document

# From test_each_phase_states_how_wide_its_answer_is.py
# Each phase states how wide its answer is, with a default that follows what it scores.
#
# A phase may write its own ``uncertainty``, with the keys of
# ``[calibration.uncertainty]``, which stays the default of every phase. Key by
# key, the phase wins, then the section, then a default read off what the phase
# scores: one mesh cell, in meters, for a phase scored only by network distances,
# and five per cent of the best cost for any other. The cell is the median
# distance between the centers of neighboring cells, measured by the network
# criterion on the mesh it scores.
#
# No solver runs. The widths are read off the configuration, the check off
# preflight, and the one search goes through an evaluator that returns a gap in
# meters and the cell it was measured on, the way the network criterion does.


SECTION = """
[calibration]
max_trials = 5

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.005, 0.35]
search_space = "log"
target = "flow.param.Sy.field.value"

[calibration.outputs.net]
support = "network"
map.complete = "streams.gpkg"

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


def _config(tmp_path: Path, *, section: str = "", k_extra: str = "", sy_extra: str = ""):
    text = SECTION + section + PHASES.format(k_extra=k_extra, sy_extra=sy_extra)
    cfg, _raw = load_toml_calibration(write_document(tmp_path, text))
    return cfg


def _widths(cfg: CalibrationConfig) -> dict[str, dict]:
    return {row["name"]: row["interval_width"] for row in phase_summaries(cfg)}


# -- the cell ----------------------------------------------------------------
def _rectangles(nrow: int, ncol: int, dx: float, dy: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (centers, face_node_connectivity) of a grid of dx by dy cells."""
    nodes_per_row = ncol + 1
    corner = (np.arange(nrow)[:, None] * nodes_per_row + np.arange(ncol)[None, :]).reshape(-1)
    connectivity = np.column_stack(
        [corner, corner + 1, corner + nodes_per_row + 1, corner + nodes_per_row]
    )
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    centres = np.column_stack([(cols + 0.5) * dx, (rows + 0.5) * dy])
    return centres, connectivity


@pytest.mark.fast
def test_one_cell_is_the_median_distance_between_neighbouring_centres() -> None:
    # Two rows of three cells, 40 m wide and 60 m tall: four pairs side by side
    # at 40 m, three pairs one above the other at 60 m. Diagonals share no edge.
    centres, connectivity = _rectangles(2, 3, dx=40.0, dy=60.0)

    assert neighbour_spacing_m(centres, connectivity) == pytest.approx(40.0)


@pytest.mark.fast
def test_the_cell_is_measured_next_to_the_mapped_cells() -> None:
    # The right column touches three pairs: two side by side at 40 m, whose
    # other cell lies outside it, and one stacked at 60 m. At least one of
    # the two cells is enough, so the median is 40 m.
    centres, connectivity = _rectangles(2, 3, dx=40.0, dy=60.0)
    touching = np.array([False, False, True, False, False, True])

    assert neighbour_spacing_m(centres, connectivity, touching=touching) == pytest.approx(40.0)
    # One corner cell alone: 40 m to its side, 60 m to the other row.
    alone = np.array([False, False, True, False, False, False])
    assert neighbour_spacing_m(centres, connectivity, touching=alone) == pytest.approx(50.0)


# -- the default follows what the phase scores ------------------------------
@pytest.mark.fast
def test_a_phase_scored_on_network_distances_takes_one_mesh_cell(tmp_path) -> None:
    width = _widths(_config(tmp_path))["k_network"]

    assert width["margin"] is None
    assert (width["kind"], width["source"], width["rule"]) == ("absolute", "default", ONE_MESH_CELL)
    assert width["on_distances"] is True


@pytest.mark.fast
def test_a_phase_scored_on_a_hydrograph_takes_five_per_cent(tmp_path) -> None:
    # The hydrograph block is not a distance, so the share of the network block
    # does not make this phase one scored on distances.
    width = _widths(_config(tmp_path))["sy_hydrograph"]

    assert (width["margin"], width["kind"]) == (0.05, "relative")
    assert (width["source"], width["rule"]) == ("default", FIVE_PER_CENT)


@pytest.mark.fast
def test_a_transformed_distance_is_no_longer_in_metres(tmp_path) -> None:
    text = SECTION.replace(
        'metric = "distance_gap"\nuses_outputs = ["net"]',
        'metric = "distance_gap"\nuses_outputs = ["net"]\ncost_transform = "log"',
    ) + PHASES.format(k_extra="", sy_extra="")
    cfg, _raw = load_toml_calibration(write_document(tmp_path, text))

    width = _widths(cfg)["k_network"]

    assert (width["margin"], width["kind"], width["on_distances"]) == (0.05, "relative", False)


@pytest.mark.fast
def test_the_section_applies_to_the_phases_it_can_bound_and_to_no_other(tmp_path) -> None:
    cfg = _config(tmp_path, section='\n[calibration.uncertainty]\ncost_margin = "150 m"\n')
    widths = _widths(cfg)

    assert (widths["k_network"]["margin"], widths["k_network"]["kind"]) == (150.0, "absolute")
    assert widths["k_network"]["source"] == "section"
    # A length bounds a distance: the hydrograph phase reads its own default.
    assert (widths["sy_hydrograph"]["margin"], widths["sy_hydrograph"]["kind"]) == (
        0.05,
        "relative",
    )
    assert widths["sy_hydrograph"]["source"] == "default"


@pytest.mark.fast
def test_a_share_in_the_section_applies_to_every_phase_that_can_read_it(tmp_path) -> None:
    cfg = _config(tmp_path, section='\n[calibration.uncertainty]\ncost_margin = "8%"\n')

    assert [
        (width["margin"], width["kind"], width["source"]) for width in _widths(cfg).values()
    ] == [(pytest.approx(0.08), "relative", "section")] * 2


@pytest.mark.fast
def test_a_value_written_in_the_phase_wins_over_the_section_and_the_default(tmp_path) -> None:
    cfg = _config(
        tmp_path,
        section='\n[calibration.uncertainty]\ncost_margin = "150 m"\n',
        k_extra='uncertainty = { cost_margin = "225 m" }',
        sy_extra='uncertainty = { cost_margin = "10%" }',
    )
    widths = _widths(cfg)

    assert (widths["k_network"]["margin"], widths["k_network"]["source"]) == (225.0, "phase")
    assert (widths["sy_hydrograph"]["margin"], widths["sy_hydrograph"]["kind"]) == (
        pytest.approx(0.1),
        "relative",
    )
    assert widths["sy_hydrograph"]["source"] == "phase"
    # The phase runs under its own keys, the section's filling the others.
    k_phase = next(decl for decl in cfg.phases if decl.name == "k_network")
    assert _phase_config(cfg, k_phase).uncertainty.cost_margin == "225 m"
    sy_phase = next(decl for decl in cfg.phases if decl.name == "sy_hydrograph")
    assert _phase_config(cfg, sy_phase).uncertainty.cost_margin == "10%"


@pytest.mark.fast
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


@pytest.mark.fast
def test_a_phase_uncertainty_that_does_not_hold_over_the_section_is_refused(tmp_path) -> None:
    with pytest.raises(Exception, match="phase 'k_network' writes an uncertainty"):
        _config(tmp_path, k_extra='uncertainty = { method = "multistart" }')


@pytest.mark.fast
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


@pytest.mark.fast
def test_the_width_does_not_enter_the_params_hash(tmp_path) -> None:
    # The width is read off the trials after the search and changes no cost, so
    # a new width re-solves nothing.
    plain = _config(tmp_path)
    widened = plain.model_copy(
        update={"uncertainty": plain.uncertainty.model_copy(update={"cost_margin": "300 m"})}
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
    path = write_document(tmp_path, text)
    return preflight_calibration(HydroModPyConfig.from_toml(path), source=path)


def _width_findings(findings: list) -> list:
    return [item for item in findings if "fraction of a distance" in item.detail]


@pytest.mark.fast
def test_check_passes_the_defaults(tmp_path) -> None:
    assert _width_findings(_check(tmp_path)) == []


@pytest.mark.fast
def test_check_refuses_a_relative_width_written_in_a_network_phase(tmp_path) -> None:
    findings = _width_findings(_check(tmp_path, k_extra='uncertainty = { cost_margin = "5%" }'))

    assert [(item.severity, item.where) for item in findings] == [
        ("error", "[[calibration.phases]] 'k_network'")
    ]
    assert "written in this phase" in findings[0].detail


@pytest.mark.fast
def test_check_refuses_a_relative_width_the_section_hands_a_network_phase(tmp_path) -> None:
    # The hydrograph phase takes the same relative width and is not named.
    findings = _width_findings(
        _check(tmp_path, section='\n[calibration.uncertainty]\ncost_margin = "5%"\n')
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
search_space = "log"
path = "flow.param.K.field.value"
"""

SINGLE_METRIC_PHASE = """
[calibration]

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"

[[calibration.phases]]
name = "k_gap"
parameters = ["K"]
objective = "distance_gap"
{uncertainty}
"""


@pytest.mark.fast
@pytest.mark.parametrize(
    ("template", "phase"),
    [(SINGLE_METRIC_SECTION, False), (SINGLE_METRIC_PHASE, True)],
    ids=["section", "phase"],
)
def test_a_single_metric_distance_takes_one_mesh_cell(tmp_path, template, phase) -> None:
    cfg, _raw = load_toml_calibration(write_document(tmp_path, template.format(uncertainty="")))

    width = cfg.interval_width_for(cfg.phases[0] if phase else None)

    assert (width.margin, width.kind, width.rule) == (None, "absolute", ONE_MESH_CELL)


@pytest.mark.fast
@pytest.mark.parametrize(
    ("template", "uncertainty", "where"),
    [
        (
            SINGLE_METRIC_SECTION,
            '\n[calibration.uncertainty]\ncost_margin = "5%"\n',
            "[calibration.uncertainty]",
        ),
        (
            SINGLE_METRIC_PHASE,
            'uncertainty = { cost_margin = "5%" }',
            "[[calibration.phases]] 'k_gap'",
        ),
    ],
    ids=["section", "phase"],
)
def test_check_refuses_a_relative_width_on_a_single_metric_distance(
    tmp_path, template, uncertainty, where
) -> None:
    path = write_document(
        tmp_path, PROJECT.format(root=tmp_path) + template.format(uncertainty=uncertainty)
    )

    findings = _width_findings(preflight_calibration(HydroModPyConfig.from_toml(path), source=path))

    assert [(item.severity, item.where) for item in findings] == [("error", where)]


@pytest.mark.fast
def test_list_phases_says_where_each_width_comes_from(tmp_path, capsys) -> None:
    text = SECTION + '\n[calibration.uncertainty]\ncost_margin = "150 m"\n'
    path = write_document(tmp_path, text + PHASES.format(k_extra="", sy_extra=""))
    calibrate_cmd.run(
        argparse.Namespace(config=path, check=False, list_phases=True, phase=None, profile=None)
    )

    # A block the phase compares prints an indented line under its own; keep
    # only the phase lines, one per phase.
    k_line, sy_line = (
        line for line in capsys.readouterr().out.splitlines() if not line.startswith(" ")
    )
    assert k_line.split("\t")[4] == "width 150 m (written in [calibration.uncertainty])"
    assert sy_line.split("\t")[4] == "width 5 % of the best cost (default)"


# -- the run reads the cell off its trials and reports the width it used ----
class _GapInMetres:
    """A network gap in meters, zero at K = 10 ** root, measured on 60 m cells."""

    evaluator_id = "test_gap_in_metres"
    needs_prepared_model = False
    root = -5.0

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        signed = (math.log10(float(request.values["K"])) - self.root) * 100.0
        return TrialOutcome(
            cost=abs(signed),
            status="completed",
            duration_s=0.0,
            components={"net.cell_spacing_m": 60.0, "net.J_signed": signed},
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
max_trials = 9
evaluator = "test_gap_in_metres"
use_cache = false
method_options = {{ points_per_dim = 9 }}
{uncertainty}

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
map.complete = "streams.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


def _run(tmp_path: Path, uncertainty: str = ""):
    path = write_document(tmp_path, SINGLE_SEARCH.format(uncertainty=uncertainty))
    return run_calibration_cli(path, workspace=tmp_path)


@pytest.mark.fast
def test_the_run_reads_one_mesh_cell_off_the_trials(tmp_path, gap_in_metres) -> None:
    report = _run(tmp_path)

    width = report.extra["interval_width"]
    assert (width["margin"], width["kind"]) == (60.0, "absolute")
    assert (width["source"], width["rule"]) == ("default", ONE_MESH_CELL)
    (interval,) = report.extra["parameter_intervals"]
    assert interval["threshold"] == pytest.approx(report.best_cost + 60.0)
    assert interval["kind"] == "absolute"
    kept = read_session(report.session_dir).widths["K"].interval
    assert (kept.lower, kept.upper) == pytest.approx((10.0**-5.5, 10.0**-4.5))
    assert (kept.margin, kept.threshold, kept.n_within, kept.n_trials) == (60.0, 60.0, 3, 9)
    assert (kept.kind, kept.lower_end, kept.upper_end) == ("absolute", "open", "open")


@pytest.mark.fast
def test_the_run_reports_a_written_width_and_where_it_was_written(tmp_path, gap_in_metres) -> None:
    report = _run(tmp_path, '\n[calibration.uncertainty]\ncost_margin = "120 m"\n')

    width = report.extra["interval_width"]
    assert (width["margin"], width["source"]) == (120.0, "section")
    (interval,) = report.extra["parameter_intervals"]
    assert interval["threshold"] == pytest.approx(report.best_cost + 120.0)


@pytest.mark.parametrize(
    ("root", "status", "note"),
    [
        (-5.1, "completed", None),
        (-2.5, "partial", "OUTSIDE the declared bounds of K, [1e-07, 0.001]"),
    ],
    ids=["inside", "outside"],
)
def test_a_root_search_reads_its_width_on_its_curve(
    tmp_path, gap_in_metres, monkeypatch, root, status, note
) -> None:
    monkeypatch.setattr(_GapInMetres, "root", root)
    text = (
        SINGLE_SEARCH.format(uncertainty="")
        .replace('"grid"', '"bisection"')
        .replace("points_per_dim = 9", "sweep_points = 5")
        .replace("max_trials = 9", "max_trials = 40")
    )
    report = run_calibration_cli(write_document(tmp_path, text), workspace=tmp_path)

    descriptor = read_session(report.session_dir)
    assert (report.status, descriptor.status) == (status, status)
    if note is not None:
        assert note in descriptor.error_message
        assert note in descriptor.stop_note
        return
    interval = descriptor.widths["K"].interval
    assert (interval.lower_end, interval.upper_end) == ("crossed", "crossed")
    # A slope of 100 m a decade and a cell of 60 m: 0.6 decade on each side.
    assert interval.lower == pytest.approx(10.0**-5.7, rel=0.02)
    assert interval.upper == pytest.approx(10.0**-4.5, rel=0.02)


class _OnARidge:
    """A cost that only sees ``a - b``, so its low trials lie on a line."""

    evaluator_id = "test_on_a_ridge"
    needs_prepared_model = False

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        cost = 1.0 + abs(float(request.values["a"]) - float(request.values["b"]))
        return TrialOutcome(cost=cost, status="completed", duration_s=0.0)


RIDGE = """
[calibration]
method = "grid"
max_trials = 36
evaluator = "test_on_a_ridge"
method_options = { points_per_dim = 6 }

[calibration.parameters.a]
bounds = [0.0, 4.0]
path = "flow.param.K.field.value"

[calibration.parameters.b]
bounds = [0.0, 4.0]
path = "flow.param.Sy.field.value"
"""


def test_a_ridge_shows_under_the_margin_on_a_grid_that_hides_it(tmp_path) -> None:
    evaluation_registry.register(_OnARidge, replace=True)
    try:
        report = run_calibration_cli(write_document(tmp_path, RIDGE), workspace=tmp_path)
    finally:
        evaluation_registry.unregister(_OnARidge.evaluator_id)

    assert report.extra["correlated_parameters"] == [("a", "b", pytest.approx(1.0))]
    widths = read_session(report.session_dir).widths
    assert widths["a"].correlated == {"b": pytest.approx(1.0)}
    assert widths["b"].correlated == {"a": pytest.approx(1.0)}


_BOWL = ((0.0, 10.0), (1.0, 4.0), (2.0, 1.0), (3.0, 2.0), (4.0, 9.0))
_TWO_BASINS = ((1.0, 1.0), (2.0, 9.0), (3.0, 1.0))
_ROOT_AT_THE_BOUND = ((0.0, 1.0), (1.0, 2.0), (2.0, 9.0))
_UNSOLVED_BESIDE_THE_ROOT = ((0.0, 10.0), (1.0, None), (2.0, 1.0), (3.0, 2.0), (4.0, 9.0))
_SCALES = {"log": lambda x: 10.0**x, "identity": lambda x: x}


@pytest.mark.parametrize(
    ("curve", "root", "margin", "kind", "scale", "ends", "expected"),
    [
        # Each crossing is interpolated between the two trials around it.
        (_BOWL, 2, 2.0, "absolute", "log", ("crossed", "crossed"), (4 / 3, 22 / 7, 3.0, 2, 5)),
        (_BOWL, 2, 0.5, "relative", "log", ("crossed", "crossed"), (11 / 6, 2.5, 1.5, 1, 5)),
        # A second basin past the crossing stays out, where an envelope would take it.
        (_TWO_BASINS, 2, 1.0, "absolute", "log", ("crossed", "bound"), (2.875, 3.0, 2.0, 1, 3)),
        # A root on the declared bound has no lower side to walk, in a linear variable.
        (
            _ROOT_AT_THE_BOUND,
            0,
            2.0,
            "absolute",
            "identity",
            ("bound", "crossed"),
            (0.0, 8 / 7, 3.0, 2, 3),
        ),
        # A trial that did not solve stops the walk where it stands.
        (
            _UNSOLVED_BESIDE_THE_ROOT,
            2,
            2.0,
            "absolute",
            "log",
            ("open", "crossed"),
            (2.0, 22 / 7, 3.0, 2, 4),
        ),
    ],
)
def test_the_root_interval_walks_the_curve(
    curve, root, margin, kind, scale, ends, expected
) -> None:
    parameter = SimpleNamespace(name="K", to_physical=_SCALES[scale])
    declared = (0.0, curve[-1][0])

    found = root_interval(curve, curve[root], margin, kind, parameter, declared).to_dict()

    lower, upper, *counts = expected
    assert (found["name"], found["lower_end"], found["upper_end"]) == ("K", *ends)
    assert found["best"] == pytest.approx(_SCALES[scale](curve[root][0]))
    assert (found["lower"], found["upper"]) == pytest.approx(
        (_SCALES[scale](lower), _SCALES[scale](upper))
    )
    assert [found["threshold"], found["n_within"], found["n_trials"]] == counts
    assert found["reaches_upper_bound"] is (ends[1] == "bound")


# From test_margin_intervals.py
# A calibrated value on its own says nothing about how well it is determined.
#
# The report gives one number per parameter. Two searches can return the same
# number with entirely different standing: one where the cost climbs steeply on
# both sides, one where it is flat over three decades. Nothing in the output told
# them apart, so a conductivity read off a report carried no way to know whether
# the record constrained it.
#
# The interval is read off the trials the search already ran: the range of values
# whose cost stays within a stated margin of the best. It assumes no error
# model and costs nothing extra, and it says explicitly when it runs into the
# search bound, because there the record does not constrain the parameter at all.


def _trace(pairs: list[tuple[float, float]]) -> list[dict[str, object]]:
    return [
        {"iter": i, "parameters": {"K": value}, "cost": cost}
        for i, (value, cost) in enumerate(pairs)
    ]


_SHARP = _trace([(1.0, 10.0), (2.0, 1.0), (3.0, 1.02), (4.0, 9.0), (5.0, 30.0)])
_FLAT = _trace([(1.0, 1.01), (2.0, 1.0), (3.0, 1.02), (4.0, 1.01), (5.0, 1.03)])


def test_the_interval_is_the_range_that_stays_within_the_margin() -> None:
    (interval,) = margin_intervals(_SHARP, bounds={"K": (0.5, 6.0)})

    assert interval.name == "K"
    assert interval.best == 2.0
    assert interval.lower == 2.0
    assert interval.upper == 3.0
    assert interval.n_within == 2


def test_a_flat_cost_gives_an_interval_that_spans_the_search() -> None:
    (interval,) = margin_intervals(_FLAT, bounds={"K": (0.5, 6.0)})

    assert interval.lower == 1.0
    assert interval.upper == 5.0
    assert interval.n_within == 5


def test_an_interval_reaching_the_search_bound_says_so() -> None:
    """There the record does not constrain the parameter; it ran out of room."""
    (interval,) = margin_intervals(_FLAT, bounds={"K": (1.0, 5.0)})

    assert interval.reaches_lower_bound is True
    assert interval.reaches_upper_bound is True


def test_an_interval_inside_the_search_does_not_claim_a_bound() -> None:
    (interval,) = margin_intervals(_SHARP, bounds={"K": (0.5, 6.0)})

    assert interval.reaches_lower_bound is False
    assert interval.reaches_upper_bound is False


def test_the_margin_is_relative_to_the_best_cost_by_default() -> None:
    assert DEFAULT_MARGIN == 0.05

    (tight,) = margin_intervals(_SHARP, margin=0.001)

    assert tight.lower == tight.upper == 2.0
    assert tight.n_within == 1


def test_an_absolute_margin_is_read_in_cost_units() -> None:
    (interval,) = margin_intervals(_SHARP, margin=8.5, kind="absolute")

    assert interval.lower == 2.0
    assert interval.upper == 4.0


def test_a_cost_that_reaches_zero_refuses_a_relative_margin() -> None:
    """A gap criterion is solved at zero, where 5 % of the best means nothing."""
    trace = _trace([(1.0, 4.0), (2.0, 0.0), (3.0, 3.0)])

    with pytest.raises(ValueError, match="length"):
        margin_intervals(trace)


def test_failed_trials_are_left_out() -> None:
    trace = _SHARP + _trace([(9.0, float("nan")), (10.0, float("inf"))])

    (interval,) = margin_intervals(trace, bounds={"K": (0.5, 6.0)})

    assert interval.upper == 3.0


def test_a_trace_with_nothing_finite_yields_nothing() -> None:
    assert margin_intervals(_trace([(1.0, float("nan"))])) == []


def test_the_interval_carries_how_many_trials_it_rests_on() -> None:
    (interval,) = margin_intervals(_SHARP)

    assert interval.n_trials == 5
    assert interval.margin == DEFAULT_MARGIN
    assert interval.kind == "relative"


def test_each_calibrated_parameter_gets_its_own_interval() -> None:
    trace = [
        {"iter": 0, "parameters": {"K": 1.0, "Sy": 0.1}, "cost": 5.0},
        {"iter": 1, "parameters": {"K": 2.0, "Sy": 0.2}, "cost": 1.0},
        {"iter": 2, "parameters": {"K": 3.0, "Sy": 0.3}, "cost": 1.01},
    ]

    intervals = {item.name: item for item in margin_intervals(trace)}

    assert set(intervals) == {"K", "Sy"}
    assert intervals["Sy"].lower == 0.2
    assert intervals["Sy"].upper == 0.3
