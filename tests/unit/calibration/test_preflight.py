"""Everything a calibration needs, checked before the first solve.

A calibration is hours of solver time. Until now every check fired where it sat:
a missing stream geometry when the criterion first ran, a typo in a parameter
path at the first trial, a phase that cannot describe a runnable calibration
when its turn came, after the phases before it had spent their whole budget.
Each one cost the run that had already happened.

Preflight runs the static checks together, before anything solves, and reports
every problem rather than the first: a file with three mistakes takes one pass
to fix instead of three overnight runs.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.calibration.preflight import PreflightFinding, preflight_calibration
from hydromodpy.config import HydroModPyConfig

_BASE = """
[workspace]
project_root = "PROJECT_ROOT"

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

_GOOD = """
[calibration]
method = "grid"
max_iter = 4

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"
"""


def _write(tmp_path: Path, calibration: str) -> Path:
    path = tmp_path / "calib.toml"
    path.write_text((_BASE + calibration).replace("PROJECT_ROOT", str(tmp_path)), encoding="utf-8")
    return path


def _preflight(path: Path):
    """Load the way the CLI does, then check; loading lives a layer above."""
    try:
        cfg = HydroModPyConfig.from_toml(path)
    except Exception as exc:
        return [PreflightFinding("error", path.name, f"the file does not load: {exc}")]
    return preflight_calibration(cfg, source=path)


def _messages(findings) -> str:
    return " | ".join(f"{item.where}: {item.detail}" for item in findings)


class TestAFileThatIsFine:
    def test_it_reports_nothing(self, tmp_path) -> None:
        assert _preflight(_write(tmp_path, _GOOD)) == []


class TestParameters:
    def test_a_path_the_configuration_does_not_carry_is_named(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.Kh]
                bounds = [1e-7, 1e-3]
                path = "flow.param.Kh.field.value"
                """,
            )
        )

        assert "flow.param.Kh.field.value" in _messages(findings)

    def test_bounds_the_wrong_way_round_are_named(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.K]
                bounds = [1e-3, 1e-7]
                path = "flow.param.K.field.value"
                """,
            )
        )

        assert findings
        assert "bounds" in _messages(findings)

    def test_a_bound_outside_the_physical_range_is_named(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.Sy]
                bounds = [1e-4, 0.8]
                path = "flow.param.Sy.field.value"
                units = "-"
                """,
            )
        )

        assert findings
        assert "Sy" in _messages(findings)


class TestOutputs:
    def test_a_stream_geometry_that_is_not_there_is_named(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.K]
                bounds = [1e-7, 1e-3]
                path = "flow.param.K.field.value"

                [calibration.outputs.net]
                support = "network"
                stream_geometry_path = "nowhere.gpkg"

                [[calibration.objective_blocks]]
                name = "gap"
                metric = "distance_gap"
                uses_outputs = ["net"]
                """,
            )
        )

        assert "nowhere.gpkg" in _messages(findings)

    def test_an_observed_network_source_the_project_does_not_carry_is_named(self, tmp_path) -> None:
        """Paired with an unrelated fault: neither may crowd out the other."""
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.K]
                bounds = [1e-3, 1e-7]
                path = "flow.param.K.field.value"

                [calibration.outputs.net]
                support = "network"
                observed_network = "geographic.river_network"

                [[calibration.objective_blocks]]
                name = "gap"
                metric = "distance_gap"
                uses_outputs = ["net"]
                """,
            )
        )

        messages = _messages(findings)
        assert "geographic.river_network" in messages
        assert "bounds" in messages

    def test_a_block_using_an_output_nobody_declared_is_named(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.K]
                bounds = [1e-7, 1e-3]
                path = "flow.param.K.field.value"

                [[calibration.objective_blocks]]
                name = "gap"
                metric = "rmse"
                uses_outputs = ["ghost"]
                """,
            )
        )

        assert "ghost" in _messages(findings)


class TestPhases:
    _PHASES = """
    [calibration]
    method = "grid"

    [calibration.parameters.K]
    bounds = [1e-7, 1e-3]
    path = "flow.param.K.field.value"

    [calibration.parameters.Sy]
    bounds = [1e-3, 0.35]
    path = "flow.param.Sy.field.value"
    units = "-"

    [[calibration.phases]]
    name = "one"
    method = "grid"
    parameters = ["{first}"]

    [[calibration.phases]]
    name = "two"
    method = "grid"
    parameters = ["Sy"]
    depends_on = "{depends}"
    """

    def test_a_phase_moving_a_parameter_nobody_declared_is_named(self, tmp_path) -> None:
        findings = _preflight(_write(tmp_path, self._PHASES.format(first="ghost", depends="one")))

        assert "ghost" in _messages(findings)

    def test_a_dependency_that_does_not_exist_is_named(self, tmp_path) -> None:
        findings = _preflight(_write(tmp_path, self._PHASES.format(first="K", depends="nowhere")))

        assert "nowhere" in _messages(findings)


class TestItReportsEverythingAtOnce:
    def test_three_mistakes_come_back_together(self, tmp_path) -> None:
        findings = _preflight(
            _write(
                tmp_path,
                """
                [calibration]
                method = "grid"

                [calibration.parameters.Kh]
                bounds = [1e-3, 1e-7]
                path = "flow.param.Kh.field.value"

                [[calibration.objective_blocks]]
                name = "gap"
                metric = "rmse"
                uses_outputs = ["ghost"]
                """,
            )
        )

        assert len(findings) >= 3


class TestAFileThatWillNotLoad:
    def test_it_says_so_once_rather_than_guessing(self, tmp_path) -> None:
        path = tmp_path / "broken.toml"
        path.write_text("[calibration]\nnot_a_key = 1\n", encoding="utf-8")

        findings = _preflight(path)

        assert len(findings) == 1
        assert findings[0].severity == "error"

    def test_a_file_without_a_calibration_section_says_so(self, tmp_path) -> None:
        path = tmp_path / "plain.toml"
        path.write_text(_BASE.replace("PROJECT_ROOT", str(tmp_path)), encoding="utf-8")

        findings = _preflight(path)

        assert "calibration" in _messages(findings)


class TestALinearizedWidth:
    """A width is built after the last solve, so what forbids it is checked first."""

    _LINEARIZED = """
[calibration]
method = "grid"
max_iter = 4
warmup_periods = WARMUP

[calibration.uncertainty]
method = "linearized"
perturbation = 0.01

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[calibration.outputs.gauge]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observes = "NANCON"
"""

    def _findings(self, tmp_path, warmup: int):
        return _preflight(_write(tmp_path, self._LINEARIZED.replace("WARMUP", str(warmup))))

    def test_a_burn_in_is_refused_before_the_first_solve(self, tmp_path) -> None:
        findings = self._findings(tmp_path, 6)

        assert any(item.severity == "error" for item in findings)
        assert "warmup_periods drops the first 6" in _messages(findings)

    def test_without_one_the_width_is_not_refused(self, tmp_path) -> None:
        # A purely negative assertion (the burn-in message is absent) would
        # also pass if the whole check disappeared. Assert the document
        # comes back clean instead, a presence: nothing at all is wrong here.
        assert self._findings(tmp_path, 0) == []


class TestALinearizedWidthOnAPhasedDocument:
    """A phased document gets one width per phase (D234), checked phase by phase.

    ``p1`` scores ``block1``, which inherits the calibration-wide burn-in and
    is refused for it; ``p2`` scores ``block2``, which turns its own burn-in
    off and is clean. A blanket, document-wide check would either refuse both
    or neither; only a per-phase one tells them apart.
    """

    _PHASED = """
[calibration]
method = "grid"
max_iter = 4
warmup_periods = 6

[calibration.uncertainty]
method = "linearized"
perturbation = 0.01

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[calibration.parameters.Sy]
bounds = [1e-3, 0.35]
path = "flow.param.Sy.field.value"
units = "-"

[calibration.outputs.gauge1]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observes = "NANCON1"

[calibration.outputs.gauge2]
variable = "head"
support = "point"
x = 100.0
y = 0.0
observes = "NANCON2"

[[calibration.objective_blocks]]
name = "block1"
metric = "rmse"
uses_outputs = ["gauge1"]
normalize_cost = true

[[calibration.objective_blocks]]
name = "block2"
metric = "rmse"
uses_outputs = ["gauge2"]
normalize_cost = true
warmup = 0

[[calibration.phases]]
name = "p1"
method = "grid"
max_iter = 4
parameters = ["K"]
outputs = ["gauge1"]
objective_blocks = ["block1"]

[[calibration.phases]]
name = "p2"
method = "grid"
max_iter = 4
parameters = ["Sy"]
outputs = ["gauge2"]
objective_blocks = ["block2"]
depends_on = "p1"
"""

    def test_the_burn_in_is_refused_on_the_phase_that_carries_it(self, tmp_path) -> None:
        findings = _preflight(_write(tmp_path, self._PHASED))

        # block1 declares no warmup of its own, so it inherits the
        # calibration-wide warmup_periods and the message names the block,
        # not the [calibration] key -- "block(s) block1 drops N ...".
        named = [item for item in findings if "block1" in item.detail and "drops" in item.detail]
        assert len(named) == 1
        assert named[0].where == "[[calibration.phases]] 'p1'"

    def test_a_phase_whose_own_block_turns_the_burn_in_off_is_not_named(self, tmp_path) -> None:
        findings = _preflight(_write(tmp_path, self._PHASED))

        assert "[[calibration.phases]] 'p2'" not in {item.where for item in findings}


class TestALinearizedWidthOnAPhaseThatNamesNeitherOutputsNorBlocks:
    """A phase naming nothing reads every declared output (``_phase_config``'s

    own default), not only what some OTHER phase's block happens to read. A
    resolved, non-empty block list is not the same fact as this phase having
    named one, and only the latter narrows the outputs this phase scores.
    """

    _DOC = """
[calibration]
method = "grid"
max_iter = 4

[calibration.uncertainty]
method = "linearized"
perturbation = 0.01

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[calibration.outputs.gauge]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observes = "NANCON"

[calibration.outputs.other]
variable = "head"
support = "point"
x = 100.0
y = 0.0

[[calibration.objective_blocks]]
name = "block_other"
metric = "rmse"
uses_outputs = ["other"]
normalize_cost = true

[[calibration.phases]]
name = "p1"
method = "grid"
max_iter = 4
parameters = ["K"]
"""

    def test_an_output_no_block_reads_still_counts_when_the_phase_names_nothing(
        self, tmp_path
    ) -> None:
        findings = _preflight(_write(tmp_path, self._DOC))

        assert findings == []


class TestALinearizedWidthOnASingleMetricPhase:
    """A single-metric phase builds no residual vector, ever: ``_phase_config``

    empties its ``outputs`` unconditionally when it declares its own
    ``variable``/``objective``, so the remedy pointed at for a document-level
    failure -- declare ``observes`` on an output -- is not one here, whatever
    the schema does or does not forbid on that phase's own selection.
    """

    _DOC = """
[calibration]
method = "grid"
max_iter = 4

[calibration.uncertainty]
method = "linearized"
perturbation = 0.01

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[[calibration.phases]]
name = "p1"
method = "grid"
max_iter = 4
parameters = ["K"]
variable = "discharge"
objective = "nse"
"""

    def test_the_message_never_points_at_a_field_the_schema_forbids(self, tmp_path) -> None:
        # Negative control: put back the literal old branch (`"and the schema
        # forbids naming a station on the outputs of a single-metric phase, so
        # that is not a remedy here"` instead of the `_phase_config` mechanism)
        # and both assertions below go red.
        findings = _preflight(_write(tmp_path, self._DOC))

        detail = _messages(findings)
        assert "cost_profile" in detail
        assert "schema forbids" not in detail
        assert "declare observes" not in detail.lower()


class TestASingleMetricPhaseAlongsideAGloballyObservedOutput:
    """The document DOES name a station -- on its global output -- while the

    single-metric phase still gets no width. ``_phase_config`` empties a
    single-metric phase's ``outputs`` unconditionally, so what the rest of the
    file declares on ``gauge`` is irrelevant to ``p1``; the message must not
    read as if the document had never named a station anywhere.

    ``p2`` scores ``b1``, which reads ``gauge`` and its declared station: it
    gets no finding, proving the document as a whole is not at fault.
    """

    _DOC = """
[calibration]
method = "grid"
max_iter = 4

[calibration.uncertainty]
method = "linearized"
perturbation = 0.01

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[calibration.outputs.gauge]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observes = "NANCON"

[[calibration.objective_blocks]]
name = "b1"
metric = "rmse"
uses_outputs = ["gauge"]
normalize_cost = true

[[calibration.phases]]
name = "p1"
method = "grid"
max_iter = 4
parameters = ["K"]
variable = "discharge"
objective = "nse"
freeze_on_success = false

[[calibration.phases]]
name = "p2"
method = "grid"
max_iter = 4
parameters = ["K"]
objective_blocks = ["b1"]
"""

    def test_p1_is_refused_without_claiming_the_document_never_named_a_station(
        self, tmp_path
    ) -> None:
        # Asserted on a presence, not an absence. An absence passes under the
        # mutation that matters here -- dropping the single-metric branch and
        # emitting the generic detail, which says "no output names a station"
        # on a document that names one, and which contains neither the old
        # false clause nor anything else these assertions would catch.
        findings = _preflight(_write(tmp_path, self._DOC))

        p1 = [item for item in findings if item.where == "[[calibration.phases]] 'p1'"]
        assert len(p1) == 1
        assert "inherits none of the calibration's outputs" in p1[0].detail
        assert "_phase_config" in p1[0].detail
        assert "schema forbids naming a station" not in p1[0].detail
        assert "cost_profile" in p1[0].detail

    def test_p2_is_not_named_because_its_block_reads_the_named_station(self, tmp_path) -> None:
        findings = _preflight(_write(tmp_path, self._DOC))

        assert "[[calibration.phases]] 'p2'" not in {item.where for item in findings}
