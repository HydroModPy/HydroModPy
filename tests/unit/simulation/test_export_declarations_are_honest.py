"""An export setting has to do what its name says, or say that it cannot.

Three defects lived here, each silent: a toggle that wrote nothing, a
declared format that let its bytes land under another extension, and a
timestep selector that collapsed without a word. The first and third are now
refused at config-validation time instead of failing quietly at export time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.core.config_kit.export_spec import ExportSpec
from hydromodpy.simulation.planning.export_config import ExportConfig


class TestNoToggleThatChangesNothing:
    """A toggle enabled with nothing to write is a promise the run cannot keep."""

    def test_a_toggle_with_no_variables_is_refused(self):
        with pytest.raises(ValidationError, match="writes nothing"):
            ExportConfig(geotiff=True, variables=[])

    def test_geopackage_with_no_variables_is_refused(self):
        with pytest.raises(ValidationError, match="writes nothing"):
            ExportConfig(geopackage=True, variables=[])

    def test_csv_timeseries_does_not_need_variables(self):
        cfg = ExportConfig(csv_timeseries=True, variables=[])

        assert cfg.csv_timeseries is True

    def test_the_default_variable_list_reaches_the_export(self):
        cfg = ExportConfig(geotiff=True)

        assert cfg.variables == ["head"]

    def test_resolution_with_geopackage_alone_is_refused(self):
        """GeoPackage is a vector format: it does not size a raster."""
        with pytest.raises(ValidationError, match="sizes nothing"):
            ExportConfig(geopackage=True, resolution=10.0)


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


class TestTheCollapseIsRefusedRatherThanSilent:
    """``export.time = 'all'`` reads as a chronicle and used to write one date."""

    def test_a_multi_step_selector_with_a_raster_toggle_is_refused(self):
        with pytest.raises(ValidationError, match="one timestep per file"):
            ExportConfig(time="all", geotiff=True)

    def test_a_multi_step_selector_with_geopackage_is_refused(self):
        with pytest.raises(ValidationError, match="one timestep per file"):
            ExportConfig(time="all", geopackage=True)

    def test_a_single_step_selector_is_accepted(self):
        cfg = ExportConfig(time="last", geotiff=True)

        assert cfg.time == "last"

    def test_netcdf_alone_accepts_a_multi_step_selector(self):
        cfg = ExportConfig(time="all", netcdf=True)

        assert cfg.time == "all"
