"""Keys a guide teaches are user keys, so the user template and reference show them.

A key at the dev or expert profile is left out of ``hmp config template
--profile user`` and folded away in the parameter reference. A guide that tells
the reader to write such a key sends them to a key they cannot find.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.introspect import extract_profile
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.toml_io.generator import generate_toml
from hydromodpy.physics.flow.sinks_sources.lake import (
    BathymetryReconstructionConfig,
    FlowLakeConfig,
)
from hydromodpy.physics.flow.sinks_sources.sfr import FlowReachNetworkConfig
from hydromodpy.physics.flow.sinks_sources.wells import (
    FlowWellConfig,
    FlowWellForcingConstantConfig,
    FlowWellForcingCsvConfig,
    FlowWellLocationAbsoluteXY,
)
from hydromodpy.physics.transport.transport_config import (
    ConcentrationTransportParametersConfig,
    Modflow6PrtParametersConfig,
    ModpathParametersConfig,
)
from hydromodpy.simulation.planning.config import SimulationConfig
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.spatial.field.core._field_param_sections import FieldHeterogeneousSection
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import VerticalGridConfig
from hydromodpy.spatial.mesh.config.main import MeshCatchmentConfig

TAUGHT = [
    (FlowWellConfig, ("units", "forcing")),
    (FlowWellForcingConstantConfig, ("units",)),
    (FlowWellForcingCsvConfig, ("path_file", "date_column", "value_column", "units")),
    (FlowWellLocationAbsoluteXY, ("layer",)),
    (FlowLakeConfig, ("rainfall", "evaporation", "runoff", "inflow", "withdrawal")),
    (FlowReachNetworkConfig, ("headwater_inflow", "runoff", "rainfall", "evaporation")),
    (
        Modflow6PrtParametersConfig,
        (
            "release_zone",
            "porosity",
            "max_particles",
            "stop_time_days",
            "track_dir",
            "release_times_days",
            "track_time_step_days",
            "particle_cell_ids",
        ),
    ),
    (ModpathParametersConfig, ("zone_partic", "track_dir", "sel_slice")),
    (ConcentrationTransportParametersConfig, ("porosity", "sconc_init", "sconc_input")),
    (ResultsConfig, ("keep_solver_files",)),
    (SimulationConfig, ("results",)),
    (VerticalGridConfig, ("lay_decay", "lay_proportions")),
    (FieldHeterogeneousSection, ("values_csv_file", "csv_key_column", "csv_value_column")),
    (CalibrationConfig, ("persist_trial_series", "persist_iteration_detail")),
    (MeshCatchmentConfig, ("zone_meshing",)),
    (HydroModPyConfig, ("modflow6", "modflownwt", "analysis")),
]


@pytest.mark.parametrize(
    ("model", "name"),
    [(model, name) for model, names in TAUGHT for name in names],
    ids=lambda v: v if isinstance(v, str) else v.__name__,
)
def test_a_taught_key_is_a_user_key(model, name) -> None:
    assert extract_profile(model.model_fields[name]) is Profile.USER


def test_the_user_template_now_shows_the_structured_layers() -> None:
    text = generate_toml(modules=["modflow6"], profile="user")
    assert "lay_proportions" in text
    assert "mf6_newton" not in text


def test_a_switch_condition_is_declared_with_a_boolean() -> None:
    meta = [
        m
        for m in BathymetryReconstructionConfig.model_fields["bank_seepage"].metadata
        if isinstance(m, VisibleWhen)
    ]
    assert meta == [VisibleWhen("dynamic_area", True)]
    assert meta[0].matches(True)
    assert not meta[0].matches(False)
