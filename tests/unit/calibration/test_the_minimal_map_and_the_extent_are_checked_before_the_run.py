"""The minimal map and the extent table, checked before the first solve.

The minimal map is a file the TOML names, anchored on that TOML like the
maximal one, and refused by preflight when it is not there. An extent table
reads the timesteps of a transient run; on a search that runs steady, the
criterion would refuse it at the first trial, after the phases before it had
spent their budget.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
from tests.unit.calibration.test_preflight import _messages, _preflight, _write

_MAPS = """
[calibration.outputs.net]
support = "network"
stream_geometry_path = "{maximal}"
minimal_stream_geometry_path = "{minimal}"
{extent}
"""

_ONE_SEARCH = """
{flow}
[calibration]
method = "bisection"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[[calibration.objective_blocks]]
name = "gap"
metric = "distance_gap"
uses_outputs = ["net"]
"""

_TWO_PHASES = """
[calibration]
method = "bisection"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[calibration.parameters.Sy]
bounds = [1e-3, 0.3]
path = "flow.param.Sy.field.value"
units = "-"

[[calibration.objective_blocks]]
name = "gap"
metric = "distance_gap"
uses_outputs = ["net"]

[[calibration.phases]]
name = "k_network"
method = "bisection"
parameters = ["K"]
regime = "{regime}"
{single_metric}

[[calibration.phases]]
name = "sy_network"
method = "grid"
max_iter = 4
parameters = ["Sy"]
objective_blocks = ["gap"]
depends_on = "k_network"
"""


def _maps(tmp_path: Path) -> tuple[Path, Path]:
    maximal = tmp_path / "data" / "hydrography" / "streams.gpkg"
    minimal = tmp_path / "data" / "hydrography" / "permanent.gpkg"
    maximal.parent.mkdir(parents=True, exist_ok=True)
    maximal.write_bytes(b"maximal")
    minimal.write_bytes(b"minimal")
    return maximal, minimal


def _outputs(maximal: str, minimal: str, *, extent: bool) -> str:
    table = "[calibration.outputs.net.extent]" if extent else ""
    return _MAPS.format(maximal=maximal, minimal=minimal, extent=table)


class TestTheMinimalMap:
    def test_a_minimal_map_that_is_not_there_is_named(self, tmp_path) -> None:
        maximal, _ = _maps(tmp_path)
        doc = _ONE_SEARCH.format(flow="") + _outputs(
            maximal.as_posix(), "nowhere_permanent.gpkg", extent=False
        )

        findings = _preflight(_write(tmp_path, doc))

        named = [item for item in findings if "nowhere_permanent.gpkg" in item.detail]
        assert len(named) == 1
        assert named[0].severity == "error"
        assert named[0].where == "[calibration.outputs.net]"
        assert "minimal_stream_geometry_path" in named[0].detail

    @pytest.mark.parametrize(
        "declared", ["permanent.gpkg", "data/hydrography/permanent.gpkg", "absolute"]
    )
    def test_a_minimal_map_that_is_there_is_no_finding(self, tmp_path, declared: str) -> None:
        maximal, minimal = _maps(tmp_path)
        written = minimal.as_posix() if declared == "absolute" else declared
        doc = _ONE_SEARCH.format(flow="") + _outputs(maximal.as_posix(), written, extent=False)

        assert _preflight(_write(tmp_path, doc)) == []

    def test_a_relative_minimal_map_is_read_from_the_toml_that_declares_it(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, minimal = _maps(tmp_path)
        configs = tmp_path / "configs"
        configs.mkdir()
        path = configs / "calibration.toml"
        path.write_text(
            "[workflow]\nmode = 'calibration'\n"
            + _ONE_SEARCH.format(flow="")
            + _outputs("streams.gpkg", "../data/hydrography/permanent.gpkg", extent=False),
            encoding="utf-8",
        )
        # A working directory that holds nothing: the path must not depend on it.
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        cfg, _raw = load_toml_calibration(path)

        output = cfg.outputs["net"]
        assert Path(output.minimal_stream_geometry_path) == minimal.resolve()
        assert (
            Path(output.stream_geometry_path)
            == (tmp_path / "data" / "hydrography" / "streams.gpkg").resolve()
        )

    def test_a_bare_minimal_filename_falls_back_to_the_data_family(self, tmp_path) -> None:
        _, minimal = _maps(tmp_path)
        configs = tmp_path / "configs"
        configs.mkdir()
        path = configs / "calibration.toml"
        path.write_text(
            "[workflow]\nmode = 'calibration'\n"
            + _ONE_SEARCH.format(flow="")
            + _outputs("streams.gpkg", "permanent.gpkg", extent=False),
            encoding="utf-8",
        )

        cfg, _raw = load_toml_calibration(path)

        assert Path(cfg.outputs["net"].minimal_stream_geometry_path) == minimal.resolve()

    def test_a_minimal_map_that_resolves_to_nothing_is_left_as_declared(self, tmp_path) -> None:
        _maps(tmp_path)
        path = tmp_path / "calibration.toml"
        path.write_text(
            "[workflow]\nmode = 'calibration'\n"
            + _ONE_SEARCH.format(flow="")
            + _outputs("streams.gpkg", "nowhere.gpkg", extent=False),
            encoding="utf-8",
        )

        cfg, _raw = load_toml_calibration(path)

        assert cfg.outputs["net"].minimal_stream_geometry_path == "nowhere.gpkg"


class TestTheExtentTable:
    def _one_search(self, tmp_path: Path, *, regime: str | None, extent: bool) -> str:
        maximal, minimal = _maps(tmp_path)
        flow = f'[flow]\nflow_regime = "{regime}"\n' if regime else ""
        return _ONE_SEARCH.format(flow=flow) + _outputs(
            maximal.as_posix(), minimal.as_posix(), extent=extent
        )

    def _two_phases(
        self, tmp_path: Path, *, regime: str, single_metric: bool, extent: bool = True
    ) -> str:
        maximal, minimal = _maps(tmp_path)
        route = 'variable = "net"\nobjective = "distance_gap"' if single_metric else ""
        route = route or 'objective_blocks = ["gap"]'
        return _TWO_PHASES.format(regime=regime, single_metric=route) + _outputs(
            maximal.as_posix(), minimal.as_posix(), extent=extent
        )

    def test_a_steady_project_scoring_an_extent_is_refused(self, tmp_path) -> None:
        doc = self._one_search(tmp_path, regime="steady", extent=True)

        findings = _preflight(_write(tmp_path, doc))

        refused = [item for item in findings if "extent table" in item.detail]
        assert len(refused) == 1
        assert refused[0].severity == "error"
        assert refused[0].where == "[calibration.outputs.net]"
        assert "[flow] flow_regime" in refused[0].detail

    @pytest.mark.parametrize(("regime", "extent"), [("transient", True), ("steady", False)])
    def test_a_transient_extent_or_a_steady_state_is_no_finding(
        self, tmp_path, regime: str, extent: bool
    ) -> None:
        doc = self._one_search(tmp_path, regime=regime, extent=extent)

        assert _preflight(_write(tmp_path, doc)) == []

    def test_the_default_regime_is_transient(self, tmp_path) -> None:
        doc = self._one_search(tmp_path, regime=None, extent=True)

        assert "extent table" not in _messages(_preflight(_write(tmp_path, doc)))

    @pytest.mark.parametrize("single_metric", [False, True])
    def test_a_steady_phase_scoring_an_extent_is_refused(
        self, tmp_path, single_metric: bool
    ) -> None:
        doc = self._two_phases(tmp_path, regime="steady", single_metric=single_metric)

        findings = _preflight(_write(tmp_path, doc))

        refused = [item for item in findings if "extent table" in item.detail]
        # Only the steady phase is named; the transient one reads the extent.
        assert len(refused) == 1
        assert refused[0].where == "[calibration.outputs.net]"
        assert "'k_network'" in refused[0].detail

    def test_a_steady_phase_through_its_overrides_is_refused(self, tmp_path) -> None:
        doc = self._two_phases(tmp_path, regime="transient", single_metric=False).replace(
            'regime = "transient"', 'overrides = { "flow.flow_regime" = "steady" }'
        )

        findings = _preflight(_write(tmp_path, doc))

        refused = [item for item in findings if "extent table" in item.detail]
        assert len(refused) == 1
        assert "'k_network'" in refused[0].detail

    def test_a_transient_phase_over_a_steady_project_is_no_finding(self, tmp_path) -> None:
        doc = '[flow]\nflow_regime = "steady"\n' + self._two_phases(
            tmp_path, regime="transient", single_metric=False
        )

        findings = _preflight(_write(tmp_path, doc))

        # The second phase names no regime and inherits the steady project.
        refused = [item for item in findings if "extent table" in item.detail]
        assert [item.detail for item in refused if "'k_network'" in item.detail] == []
        assert len(refused) == 1
        assert "'sy_network'" in refused[0].detail


class TestTheMinimalObservedNetworkSource:
    """``minimal_observed_network = "data.hydrography"`` is checked as statically as the
    maximal map: a project declaring it with no ``[[data.hydrography.sources]]``
    at all is refused at preflight, not at the first trial's
    ``resolve_minimal_network`` call.
    """

    _DOC = """
    [calibration]
    method = "grid"

    [calibration.parameters.K]
    bounds = [1e-7, 1e-3]
    path = "flow.param.K.field.value"

    [calibration.outputs.net]
    support = "network"
    stream_geometry_path = "{maximal}"
    {minimal}

    [[calibration.objective_blocks]]
    name = "gap"
    metric = "distance_gap"
    uses_outputs = ["net"]
    """

    def _doc(self, tmp_path: Path, *, minimal: str) -> str:
        maximal = tmp_path / "streams.gpkg"
        maximal.write_bytes(b"maximal")
        return self._DOC.format(maximal=maximal.as_posix(), minimal=minimal)

    def test_a_minimal_source_with_no_hydrography_section_is_named(self, tmp_path) -> None:
        doc = self._doc(tmp_path, minimal='minimal_observed_network = "data.hydrography"')

        findings = _preflight(_write(tmp_path, doc))

        named = [item for item in findings if "minimal_observed_network" in item.detail]
        assert len(named) == 1
        assert named[0].severity == "error"
        assert named[0].where == "[calibration.outputs.net]"
        assert "data.hydrography.sources" in named[0].detail

    def test_a_minimal_source_with_a_hydrography_section_is_no_finding(self, tmp_path) -> None:
        doc = (
            self._doc(tmp_path, minimal='minimal_observed_network = "data.hydrography"')
            + '\n[[data.hydrography.sources]]\nsource = "bdtopage"\n'
        )

        findings = _preflight(_write(tmp_path, doc))

        assert findings == []

    def test_no_minimal_source_declared_is_no_finding(self, tmp_path) -> None:
        doc = self._doc(tmp_path, minimal="")

        findings = _preflight(_write(tmp_path, doc))

        assert findings == []
