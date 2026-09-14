"""An export setting has to do what its name says, or say that it cannot.

Three defects lived here, each silent: two toggles that changed nothing, a
declared format that let its bytes land under another extension, and a timestep
selector that collapsed without a word.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.config_kit.export_spec import ExportSpec
from hydromodpy.simulation.planning.export_config import ExportVariablesConfig


class TestNoToggleThatChangesNothing:
    """A field that gates nothing is a promise the run cannot keep."""

    def test_the_variables_config_declares_only_what_it_can_export(self):
        declared = set(ExportVariablesConfig.model_fields)

        assert declared == {"head", "concentration", "derived"}

    @pytest.mark.parametrize("dead", ["budget", "pathlines"])
    def test_a_removed_toggle_is_refused_rather_than_ignored(self, dead: str):
        """extra='forbid' turns the old silent no-op into a named error."""
        with pytest.raises(ValueError, match=dead):
            ExportVariablesConfig(**{dead: True})

    def test_every_declared_variable_reaches_the_export(self):
        names = ExportVariablesConfig(head=True, concentration=True, derived=True).active_names()

        assert "head" in names
        assert "concentration" in names
        assert {"watertable_elevation", "watertable_depth", "seepage_mask"} <= set(names)


class TestFormatAndDestinationAgree:
    """Two statements about one file; the run refuses to make them disagree."""

    def test_a_format_contradicting_the_extension_is_refused(self):
        with pytest.raises(ValueError, match="names a geotiff file"):
            ExportSpec(var="*", fmt="csv", dest=Path("/tmp/field.tif"))

    def test_a_format_matching_the_extension_passes(self):
        assert ExportSpec(var="*", fmt="csv", dest=Path("/tmp/t.csv")).fmt.value == "csv"

    def test_a_destination_without_an_extension_takes_the_declared_format(self):
        assert ExportSpec(var="*", fmt="csv", dest=Path("/tmp/t")).fmt.value == "csv"

    def test_an_omitted_format_still_comes_from_the_extension(self):
        spec = ExportSpec(var="*", dest=Path("/tmp/field.tif"), time="last")

        assert spec.fmt.value == "geotiff"

    def test_a_multi_step_selector_on_a_single_step_format_is_refused(self):
        with pytest.raises(ValueError, match="one timestep per file"):
            ExportSpec(var="head", dest=Path("/tmp/h.tif"), time="all")


class TestTheCollapseIsAnnounced:
    """export.times = 'all' reads as a chronicle and writes one date."""

    def test_the_run_says_which_timestep_a_raster_got(self, caplog):
        from hydromodpy.simulation.extraction import post_run

        recorded: list[ExportSpec] = []

        class _Store:
            project_path = Path("/tmp/hmp-export-test")

            def export(self, _sim_id, spec):
                recorded.append(spec)

            def record_export(self, *_args, **_kwargs):
                return None

        config = _export_config(times="all", geotiff=True, netcdf=True)
        with caplog.at_level("WARNING"):
            post_run._auto_export("sim", _Store(), config)

        assert "hold one per file" in caplog.text
        by_format = {spec.fmt.value: spec.time for spec in recorded}
        assert by_format.get("geotiff") == "last"
        assert by_format.get("netcdf") == "all"

    def test_a_single_step_selector_says_nothing(self, caplog):
        from hydromodpy.simulation.extraction import post_run

        class _Store:
            project_path = Path("/tmp/hmp-export-test")

            def export(self, _sim_id, _spec):
                return None

            def record_export(self, *_args, **_kwargs):
                return None

        with caplog.at_level("WARNING"):
            post_run._auto_export("sim", _Store(), _export_config(times="last", geotiff=True))

        assert "hold one per file" not in caplog.text


def _export_config(*, times, geotiff=False, netcdf=False):
    from hydromodpy.simulation.planning.export_config import ExportConfig

    return ExportConfig(times=times, geotiff=geotiff, netcdf=netcdf)
