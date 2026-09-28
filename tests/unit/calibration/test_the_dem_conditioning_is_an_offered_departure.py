"""Filling the DEM is the paper's; breaching it is a departure a file chooses.

The protocol declares the key with the paper's value, so the Methods
paragraph names it only when a file moves it off that value. The key lives
under [geographic], so the run and ``hmp calibrate --check`` read it there,
and only when the file wrote it. The solvers fall back on the same default.
"""

from __future__ import annotations

from hydromodpy.calibration.protocols import protocol_record
from hydromodpy.calibration.protocols.boilerplate import methods_paragraph

NAME = "matching_hydrographic_network"
STAGES = ["steady_conductivity"]


def _entry() -> dict:
    deviations = {item["key"]: item for item in protocol_record(NAME)["deviations"]}
    return deviations["dem_correc_type"]


def test_the_entry_pins_the_paper_s_fill() -> None:
    entry = _entry()
    assert entry["paper_value"] == "fill"
    assert "FillDepressions" in entry["paper"]
    assert "'fill' by default" in entry["here"]
    assert "'breach' is offered and departs" in entry["here"]


def test_breach_is_named_in_the_methods_paragraph() -> None:
    prose = methods_paragraph(NAME, stages_that_ran=STAGES, chosen={"dem_correc_type": "breach"})
    assert "dem_correc_type was set to 'breach'" in prose


def test_fill_is_not_read_as_a_departure() -> None:
    prose = methods_paragraph(NAME, stages_that_ran=STAGES, chosen={"dem_correc_type": "fill"})
    assert "departs from the published method" not in prose


def _paragraph(document: dict) -> str:
    from types import SimpleNamespace

    from hydromodpy.calibration.config import (
        MatchingHydrographicNetworkOptions,
        validate_calib_output,
    )
    from hydromodpy.calibration.runners.staged_runner import (
        _geographic_choices,
        _methods_paragraph_for,
    )

    net = validate_calib_output({"support": "network", "stream_geometry_path": "map.gpkg"})
    cfg = SimpleNamespace(
        protocol=MatchingHydrographicNetworkOptions(name=NAME), outputs={"net": net}
    )
    steady = SimpleNamespace(
        name="steady_conductivity",
        report=SimpleNamespace(best_parameters={"K": 1.0e-5}, best_objective=0.5, extra={}),
    )
    text = _methods_paragraph_for(cfg, [steady], [], geographic=_geographic_choices(document))
    assert text is not None
    return text


class TestTheRunReadsTheGeographicSection:
    """The key lives under [geographic], which the paragraph used never to read."""

    def test_a_file_that_breaches_is_named_in_its_methods(self) -> None:
        text = _paragraph({"geographic": {"dem_correc_type": "breach"}})

        assert "dem_correc_type was set to 'breach'" in text
        assert "FillDepressions" in text

    def test_a_file_that_writes_fill_does_not_depart(self) -> None:
        text = _paragraph({"geographic": {"dem_correc_type": "fill"}})

        assert "dem_correc_type" not in text

    def test_an_unset_key_stays_silent(self) -> None:
        assert "dem_correc_type" not in _paragraph({"geographic": {"crs_project": "EPSG:2154"}})
        assert "dem_correc_type" not in _paragraph({})


class TestTheCheckReadsWhatTheFileWrote:
    def test_a_written_breach_is_reported(self) -> None:
        from types import SimpleNamespace

        from hydromodpy.cli.commands.calibrate import _values_this_file_set
        from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

        cfg = SimpleNamespace(
            calibration=SimpleNamespace(outputs={}),
            geographic=GeographicConfig.model_construct(dem_correc_type="breach"),
        )

        assert _values_this_file_set(cfg, ["dem_correc_type"]) == {"dem_correc_type": "breach"}

    def test_the_default_left_unwritten_is_not_reported(self) -> None:
        from types import SimpleNamespace

        from hydromodpy.cli.commands.calibrate import _values_this_file_set
        from hydromodpy.spatial.geographic.geographic_config import GeographicConfig

        geographic = GeographicConfig.model_construct(crs_project="EPSG:2154")
        cfg = SimpleNamespace(calibration=SimpleNamespace(outputs={}), geographic=geographic)

        assert geographic.dem_correc_type == "fill"
        assert _values_this_file_set(cfg, ["dem_correc_type"]) == {}


class TestTheSolverFallbackFollowsTheConfig:
    """A geographic object without the key conditions the DEM as the config would."""

    def _captured(self, monkeypatch, module, call) -> dict:
        seen: dict = {}

        def fake(**kwargs):
            seen.update(kwargs)
            return "routing"

        monkeypatch.setattr(module, "build_solver_routing_context", fake)
        call()
        return seen

    def _model(self, tmp_path):
        from types import SimpleNamespace

        return SimpleNamespace(
            routing_ctx=None,
            grid_ctx=object(),
            dem_watershed_path=str(tmp_path / "dem.tif"),
            full_path=str(tmp_path),
            geographic=SimpleNamespace(),
        )

    def test_modflow6_falls_back_to_the_config_default(self, monkeypatch, tmp_path) -> None:
        from hydromodpy.solver.modflow6 import build

        model = self._model(tmp_path)
        seen = self._captured(
            monkeypatch, build, lambda: build.ensure_solver_routing_context(model)
        )

        assert seen["dem_correc_type"] == "fill"

    def test_nwt_falls_back_to_the_config_default(self, monkeypatch, tmp_path) -> None:
        from hydromodpy.solver.modflow_nwt.nwt import nwt_solver

        model = self._model(tmp_path)
        seen = self._captured(
            monkeypatch,
            nwt_solver,
            lambda: nwt_solver.ModflowNwt._ensure_solver_routing_context(model),
        )

        assert seen["dem_correc_type"] == "fill"
