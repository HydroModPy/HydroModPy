"""Width of the answer of each phase (`optim.cost_margin`).
The width is a cost margin, in meters for a network distance and in per cent
of the best cost otherwise. No solver runs.
"""

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
from hydromodpy.calibration.optim.cost_margin import ONE_MESH_CELL, margin_intervals, root_interval
from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.calibration.runners.document import load_toml_calibration
from hydromodpy.calibration.runners.staged_report import phase_summaries
from hydromodpy.calibration.runners.staged_runner import _phase_config
from hydromodpy.catchment.stream_network.geometry import neighbour_spacing_m
from hydromodpy.cli.commands import calibrate as calibrate_cmd
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.results.session.descriptor import read_session
from tests.unit.calibration._factories_runners import write_document

# The default width is one mesh cell (m) for a phase scored only by network
# distances, and 5 % of the best cost for any other. A phase key beats the
# section key, which beats the default. No solver runs.

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
def test_cell_is_median_neighbour_spacing() -> None:
    # Two rows of three cells, 40 m wide and 60 m tall: four pairs side by side
    # at 40 m, three pairs one above the other at 60 m. Diagonals share no edge.
    centres, connectivity = _rectangles(2, 3, dx=40.0, dy=60.0)

    assert neighbour_spacing_m(centres, connectivity) == pytest.approx(40.0)


@pytest.mark.fast
def test_cell_spacing_near_mapped_cells() -> None:
    # The right column touches three pairs: two side by side at 40 m, whose
    # other cell lies outside it, and one stacked at 60 m. At least one of
    # the two cells is enough, so the median is 40 m.
    centres, connectivity = _rectangles(2, 3, dx=40.0, dy=60.0)
    touching = np.array([False, False, True, False, False, True])

    assert neighbour_spacing_m(centres, connectivity, touching=touching) == pytest.approx(40.0)
    # One corner cell alone: 40 m to its side, 60 m to the other row.
    alone = np.array([False, False, True, False, False, False])
    assert neighbour_spacing_m(centres, connectivity, touching=alone) == pytest.approx(50.0)


@pytest.mark.fast
def test_section_share_reaches_every_phase(tmp_path) -> None:
    cfg = _config(tmp_path, section='\n[calibration.uncertainty]\ncost_margin = "8%"\n')

    assert [
        (width["margin"], width["kind"], width["source"]) for width in _widths(cfg).values()
    ] == [(pytest.approx(0.08), "relative", "section")] * 2


@pytest.mark.fast
def test_phase_width_wins(tmp_path) -> None:
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
def test_phase_method_drops_section_restarts(tmp_path) -> None:
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
def test_phase_uncertainty_refusal(tmp_path) -> None:
    with pytest.raises(Exception, match="phase 'k_network' writes an uncertainty"):
        _config(tmp_path, k_extra='uncertainty = { method = "multistart" }')


@pytest.mark.fast
def test_posterior_refusal() -> None:
    with pytest.raises(ValidationError, match="'posterior' is not offered"):
        CalibrationConfig.model_validate(
            {
                "parameters": {"K": {"bounds": [1e-7, 1e-3]}},
                "phases": [
                    {"name": "p", "parameters": ["K"], "uncertainty": {"method": "posterior"}}
                ],
            }
        )


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


CHECK_REFUSALS = [
    pytest.param(
        {"k_extra": 'uncertainty = { cost_margin = "5%" }'},
        "written in this phase",
        id="written in the phase",
    ),
    # The hydrograph phase takes the same relative width and is not named.
    pytest.param(
        {"section": '\n[calibration.uncertainty]\ncost_margin = "5%"\n'},
        "written in [calibration.uncertainty]",
        id="handed by the section",
    ),
]


@pytest.mark.fast
@pytest.mark.parametrize(("kwargs", "origin"), CHECK_REFUSALS)
def test_check_refuses_relative_width(tmp_path, kwargs, origin) -> None:
    findings = _width_findings(_check(tmp_path, **kwargs))

    assert [(item.severity, item.path) for item in findings] == [("error", "calibration.phases")]
    assert findings[0].detail.startswith("'k_network': ")
    assert origin in findings[0].detail


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
def test_list_phases_width_source(tmp_path, capsys) -> None:
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
    evaluation_registry.evaluators.register(_GapInMetres, replace=True)
    try:
        yield _GapInMetres
    finally:
        evaluation_registry.evaluators.unregister(_GapInMetres.evaluator_id)


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
def test_run_reads_one_mesh_cell(tmp_path, gap_in_metres) -> None:
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
def test_run_reports_written_width(tmp_path, gap_in_metres) -> None:
    report = _run(tmp_path, '\n[calibration.uncertainty]\ncost_margin = "120 m"\n')

    width = report.extra["interval_width"]
    assert (width["margin"], width["source"]) == (120.0, "section")
    (interval,) = report.extra["parameter_intervals"]
    assert interval["threshold"] == pytest.approx(report.best_cost + 120.0)


def bisect_for_root(tmp_path, monkeypatch, root):
    monkeypatch.setattr(_GapInMetres, "root", root)
    text = (
        SINGLE_SEARCH.format(uncertainty="")
        .replace('"grid"', '"bisection"')
        .replace("points_per_dim = 9", "sweep_points = 5")
        .replace("max_trials = 9", "max_trials = 40")
    )
    report = run_calibration_cli(write_document(tmp_path, text), workspace=tmp_path)
    return report, read_session(report.session_dir)


def test_root_inside_bounds(tmp_path, gap_in_metres, monkeypatch) -> None:
    report, descriptor = bisect_for_root(tmp_path, monkeypatch, -5.1)

    assert (report.status, descriptor.status) == ("completed", "completed")
    interval = descriptor.widths["K"].interval
    assert (interval.lower_end, interval.upper_end) == ("crossed", "crossed")
    # A slope of 100 m a decade and a cell of 60 m: 0.6 decade on each side.
    assert interval.lower == pytest.approx(10.0**-5.7, rel=0.02)
    assert interval.upper == pytest.approx(10.0**-4.5, rel=0.02)


def test_root_outside_bounds(tmp_path, gap_in_metres, monkeypatch) -> None:
    report, descriptor = bisect_for_root(tmp_path, monkeypatch, -2.5)

    note = "OUTSIDE the declared bounds of K, [1e-07, 0.001]"
    assert (report.status, descriptor.status) == ("partial", "partial")
    assert note in descriptor.error_message
    assert note in descriptor.stop_note


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


def test_ridge_shows_as_correlation(tmp_path) -> None:
    evaluation_registry.evaluators.register(_OnARidge, replace=True)
    try:
        report = run_calibration_cli(write_document(tmp_path, RIDGE), workspace=tmp_path)
    finally:
        evaluation_registry.evaluators.unregister(_OnARidge.evaluator_id)

    assert report.extra["correlated_parameters"] == [("a", "b", pytest.approx(1.0))]
    widths = read_session(report.session_dir).widths
    assert widths["a"].correlated == {"b": pytest.approx(1.0)}
    assert widths["b"].correlated == {"a": pytest.approx(1.0)}


_BOWL = {0.0: 10.0, 1.0: 4.0, 2.0: 1.0, 3.0: 2.0, 4.0: 9.0}
_TWO_BASINS = {1.0: 1.0, 2.0: 9.0, 3.0: 1.0}
_ROOT_AT_THE_BOUND = {0.0: 1.0, 1.0: 2.0, 2.0: 9.0}
_UNSOLVED_BESIDE_THE_ROOT = {0.0: 10.0, 1.0: None, 2.0: 1.0, 3.0: 2.0, 4.0: 9.0}
# A cost equal to the threshold is not a crossing.
_ON_THE_THRESHOLD = {0.0: 9.0, 1.0: 1.0, 2.0: 3.0}
_SCALES = {"log": lambda x: 10.0**x, "identity": lambda x: x}


@pytest.mark.parametrize(
    ("curve", "root", "margin", "kind", "scale", "ends", "expected"),
    [
        # Each crossing is interpolated between the two trials around it.
        (_BOWL, 2.0, 2.0, "absolute", "log", ("crossed", "crossed"), (4 / 3, 22 / 7, 3.0, 2, 5)),
        (_BOWL, 2.0, 0.5, "relative", "log", ("crossed", "crossed"), (11 / 6, 2.5, 1.5, 1, 5)),
        # A second basin past the crossing stays out, where an envelope would take it.
        (_TWO_BASINS, 3.0, 1.0, "absolute", "log", ("crossed", "bound"), (2.875, 3.0, 2.0, 1, 3)),
        # A root on the declared bound has no lower side to walk, in a linear variable.
        (
            _ROOT_AT_THE_BOUND,
            0.0,
            2.0,
            "absolute",
            "identity",
            ("bound", "crossed"),
            (0.0, 8 / 7, 3.0, 2, 3),
        ),
        # A trial that did not solve stops the walk where it stands.
        (
            _UNSOLVED_BESIDE_THE_ROOT,
            2.0,
            2.0,
            "absolute",
            "log",
            ("open", "crossed"),
            (2.0, 22 / 7, 3.0, 2, 4),
        ),
        (
            _ON_THE_THRESHOLD,
            1.0,
            2.0,
            "absolute",
            "identity",
            ("crossed", "bound"),
            (0.75, 2.0, 3.0, 2, 3),
        ),
    ],
)
def test_the_root_interval_walks_the_curve(
    curve, root, margin, kind, scale, ends, expected
) -> None:
    parameter = SimpleNamespace(name="K", to_physical=_SCALES[scale])
    declared = (0.0, max(curve))

    found = root_interval(curve, (root, curve[root]), margin, kind, parameter, declared).to_dict()

    lower, upper, *counts = expected
    assert (found["name"], found["lower_end"], found["upper_end"]) == ("K", *ends)
    assert found["best"] == pytest.approx(_SCALES[scale](root))
    assert (found["lower"], found["upper"]) == pytest.approx(
        (_SCALES[scale](lower), _SCALES[scale](upper))
    )
    assert [found["threshold"], found["n_within"], found["n_trials"]] == counts
    assert found["reaches_upper_bound"] is (ends[1] == "bound")
    assert (found["margin"], found["kind"]) == (margin, kind)


def test_crossing_past_declared_bound() -> None:
    parameter = SimpleNamespace(name="K", to_physical=_SCALES["identity"])

    found = root_interval({0.0: 1.0, 1.0: 9.0}, (0.0, 1.0), 1.0, "absolute", parameter, (-1.0, 0.1))

    assert found.upper == pytest.approx(0.125)
    assert (found.upper_crossed, found.reaches_upper_bound) == (True, False)


# The interval is the range of values whose cost stays within a margin of the best.


def _trace(pairs: list[tuple[float, float]]) -> list[dict[str, object]]:
    return [
        {"iter": i, "parameters": {"K": value}, "cost": cost}
        for i, (value, cost) in enumerate(pairs)
    ]


_SHARP = _trace([(1.0, 10.0), (2.0, 1.0), (3.0, 1.02), (4.0, 9.0), (5.0, 30.0)])
_FLAT = _trace([(1.0, 1.01), (2.0, 1.0), (3.0, 1.02), (4.0, 1.01), (5.0, 1.03)])


def test_interval_inside_bounds() -> None:
    (interval,) = margin_intervals(_SHARP, bounds={"K": (0.5, 6.0)})

    assert interval.reaches_lower_bound is False
    assert interval.reaches_upper_bound is False


def test_absolute_margin() -> None:
    (interval,) = margin_intervals(_SHARP, margin=8.5, kind="absolute")

    assert interval.lower == 2.0
    assert interval.upper == 4.0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [({"margin": -0.1}, "must not be negative"), ({"kind": "ratio"}, "'relative' or 'absolute'")],
)
def test_margin_refusals(kwargs, match) -> None:
    with pytest.raises(ValueError, match=match):
        margin_intervals(_SHARP, **kwargs)


NO_INTERVAL = [
    pytest.param(
        _trace([(float("nan"), 1.0), (5.0, 10.0)]),
        {"parameters": ["K", "absent"]},
        id="no finite value",
    ),
    pytest.param(_trace([(1.0, float("nan"))]), {}, id="no finite cost"),
]


@pytest.mark.parametrize(("trace", "kwargs"), NO_INTERVAL)
def test_no_interval(trace, kwargs) -> None:
    assert margin_intervals(trace, **kwargs) == []
