"""Every registered figure answers to its name, its class, its kind and its fields.

This replaces roughly ten per-figure tests, each of which called
``get("its_own_literal_name")`` and asserted the result. That shape protects
only the figures whose author remembered to write a test, and it can never
fail for a figure registered later under a wrong key, an empty key, or with a
drifting ``spec`` - nobody was there to write the case.

The table below is the registry contract, pinned once. It is checked both
ways: a figure missing from the registry fails, and a figure added to the
registry without a line here fails too. That second direction is the point -
adding a figure now forces its author to state, in one line, what the rest of
the codebase is allowed to assume about it.

``required_fields`` is the part with teeth: it is what a Run must carry before
the figure can render, so a silent change there breaks callers at render time,
far from the edit.
"""

from __future__ import annotations

import pytest

from hydromodpy.display.figure_registry import get, names

# name -> (fully qualified class, spec.kind, spec.required_fields)
REGISTRY_CONTRACT: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "accumulation_map": (
        "hydromodpy.display.figures.accumulation_map.AccumulationMap",
        "spatial",
        ("accumulation_flux",),
    ),
    "bisection_bracket_trace": (
        "hydromodpy.display.figures.bisection_bracket_trace.BisectionBracketTraceFigure",
        "timeseries",
        (),
    ),
    "boundary_package_map": (
        "hydromodpy.display.figures.boundary_package_map.BoundaryPackageMap",
        "spatial",
        (),
    ),
    "calibration_convergence": (
        "hydromodpy.display.figures.calibration_convergence.CalibrationConvergenceFigure",
        "timeseries",
        (),
    ),
    "calibration_landscape": (
        "hydromodpy.display.figures.calibration_landscape.CalibrationLandscapeFigure",
        "comparison",
        (),
    ),
    "calibration_objective_surface": (
        "hydromodpy.display.figures.calibration_objective_surface.CalibrationObjectiveSurfaceFigure",
        "comparison",
        (),
    ),
    "calibration_pairplot": (
        "hydromodpy.display.figures.calibration_pairplot.CalibrationPairplotFigure",
        "comparison",
        (),
    ),
    "calibration_posterior": (
        "hydromodpy.display.figures.calibration_posterior.CalibrationPosteriorFigure",
        "comparison",
        (),
    ),
    "calibration_trace": (
        "hydromodpy.display.figures.calibration_trace.CalibrationTraceFigure",
        "timeseries",
        (),
    ),
    "concentration_map": (
        "hydromodpy.display.figures.concentration_map.ConcentrationMap",
        "spatial",
        ("concentration",),
    ),
    "conditioning_impact_map": (
        "hydromodpy.display.figures.conditioning_impact_map.ConditioningImpactMap",
        "comparison",
        (),
    ),
    "cross_section": (
        "hydromodpy.display.figures.cross_section.CrossSection",
        "section",
        ("watertable_elevation", "topography"),
    ),
    "depression_map": ("hydromodpy.display.figures.depression_map.DepressionMap", "spatial", ()),
    "difference_map": ("hydromodpy.display.figures.difference_map.DifferenceMap", "comparison", ()),
    "downslope_distance_crossing": (
        "hydromodpy.display.figures.downslope_distance_crossing.DownslopeDistanceCrossingFigure",
        "timeseries",
        (),
    ),
    "downslope_distance_map": (
        "hydromodpy.display.figures.downslope_distance_map.DownslopeDistanceMap",
        "spatial",
        ("release_flux",),
    ),
    "duration_curve": (
        "hydromodpy.display.figures.duration_curve.DurationCurveFigure",
        "timeseries",
        (),
    ),
    "ensemble_band": (
        "hydromodpy.display.figures.ensemble_band.EnsembleBandFigure",
        "comparison",
        (),
    ),
    "flow_direction_map": (
        "hydromodpy.display.figures.flow_direction_map.FlowDirectionMap",
        "spatial",
        (),
    ),
    "flux_timeseries": ("hydromodpy.display.figures.flux_timeseries.FluxTimeseries", "balance", ()),
    "hydrograph": ("hydromodpy.display.figures.hydrograph.Hydrograph", "timeseries", ()),
    "hydrograph_log_nse": (
        "hydromodpy.display.figures.hydrograph_log_nse.HydrographLogNseFigure",
        "comparison",
        (),
    ),
    "hydrograph_sim_obs": (
        "hydromodpy.display.figures.hydrograph_sim_obs.HydrographSimObs",
        "comparison",
        (),
    ),
    "hydrographic_network_comparison": (
        "hydromodpy.display.figures.hydrographic_network_comparison.HydrographicNetworkComparisonFigure",
        "comparison",
        (),
    ),
    "hydrographic_network_generated": (
        "hydromodpy.display.figures.hydrographic_network.HydrographicNetworkGeneratedFigure",
        "comparison",
        (),
    ),
    "hydrographic_network_generated_extra_only": (
        "hydromodpy.display.figures.hydrographic_network_comparison.HydrographicNetworkGeneratedExtraOnlyFigure",
        "comparison",
        (),
    ),
    "hydrographic_network_reference": (
        "hydromodpy.display.figures.hydrographic_network.HydrographicNetworkReferenceFigure",
        "comparison",
        (),
    ),
    "hydrographic_network_reference_missing_only": (
        "hydromodpy.display.figures.hydrographic_network_comparison.HydrographicNetworkReferenceMissingOnlyFigure",
        "comparison",
        (),
    ),
    "lake_abacus_comparison": (
        "hydromodpy.display.figures.lake_abacus_comparison.LakeAbacusComparison",
        "comparison",
        (),
    ),
    "lake_stage_sim_obs": (
        "hydromodpy.display.figures.lake_level_sim_obs.LakeStageSimObs",
        "comparison",
        (),
    ),
    "lake_volume_sim_obs": (
        "hydromodpy.display.figures.lake_level_sim_obs.LakeVolumeSimObs",
        "comparison",
        (),
    ),
    "matching_hydrographic_network_card": (
        "hydromodpy.display.figures.matching_hydrographic_network_card.MatchingHydrographicNetworkCard",
        "comparison",
        (),
    ),
    "mesh_map": ("hydromodpy.display.figures.mesh_map.MeshMap", "spatial", ("topography",)),
    "parameter_cost_profile": (
        "hydromodpy.display.figures.parameter_cost_profile.ParameterCostProfileFigure",
        "timeseries",
        (),
    ),
    "particle_tracks": (
        "hydromodpy.display.figures.particle_tracks.ParticleTracks",
        "particles",
        ("particles",),
    ),
    "piezo_timeseries_sim_obs": (
        "hydromodpy.display.figures.piezo_timeseries_sim_obs.PiezoTimeseriesSimObs",
        "comparison",
        (),
    ),
    "piezometric_map": (
        "hydromodpy.display.figures.piezometric_map.PiezometricMap",
        "spatial",
        ("watertable_elevation",),
    ),
    "piper_diagram": ("hydromodpy.display.figures.piper_diagram.PiperDiagramFigure", "table", ()),
    "recession": ("hydromodpy.display.figures.recession.RecessionCurveFigure", "timeseries", ()),
    "recharge_map": (
        "hydromodpy.display.figures.recharge_map.RechargeMap",
        "spatial",
        ("recharge",),
    ),
    "residuals": ("hydromodpy.display.figures.residuals.Residuals", "comparison", ()),
    "roptim_validity_chart": (
        "hydromodpy.display.figures.roptim_validity_chart.RoptimValidityChart",
        "comparison",
        (),
    ),
    "scatter_one_to_one": (
        "hydromodpy.display.figures.scatter_one_to_one.ScatterOneToOne",
        "comparison",
        (),
    ),
    "schoeller_diagram": (
        "hydromodpy.display.figures.schoeller_diagram.SchoellerDiagramFigure",
        "table",
        (),
    ),
    "seasonal_boxplot": (
        "hydromodpy.display.figures.seasonal_boxplot.SeasonalBoxplotFigure",
        "timeseries",
        (),
    ),
    "seepage_map": (
        "hydromodpy.display.figures.seepage_map.SeepageMap",
        "spatial",
        ("seepage_mask",),
    ),
    "seepage_network_confusion_map": (
        "hydromodpy.display.figures.seepage_network_confusion_map.SeepageNetworkConfusionMap",
        "comparison",
        ("release_flux",),
    ),
    "seepage_network_reference_overlay": (
        "hydromodpy.display.figures.seepage_network_reference_overlay.SeepageNetworkReferenceOverlay",
        "comparison",
        ("release_flux",),
    ),
    "sfr_longitudinal_profile": (
        "hydromodpy.display.figures.sfr_longitudinal_profile.SfrLongitudinalProfile",
        "timeseries",
        (),
    ),
    "sfr_reach_network": (
        "hydromodpy.display.figures.sfr_reach_network.SfrReachNetwork",
        "spatial",
        (),
    ),
    "sfr_reach_timeseries": (
        "hydromodpy.display.figures.sfr_reach_timeseries.SfrReachTimeseries",
        "timeseries",
        (),
    ),
    "side_by_side": (
        "hydromodpy.display.figures.side_by_side_map.SideBySideMapFigure",
        "comparison",
        (),
    ),
    "simulated_active_network": (
        "hydromodpy.display.figures.simulated_active_network.SimulatedActiveNetworkMap",
        "spatial",
        ("accumulation_flux",),
    ),
    "simulated_active_network_reference_overlay": (
        "hydromodpy.display.figures.simulated_active_network.SimulatedActiveNetworkReferenceOverlay",
        "comparison",
        ("accumulation_flux",),
    ),
    "stiff_diagram": ("hydromodpy.display.figures.stiff_diagram.StiffDiagramFigure", "table", ()),
    "water_budget": ("hydromodpy.display.figures.water_budget.WaterBudget", "balance", ()),
    "watershed_id_card": (
        "hydromodpy.display.figures.watershed_id_card.WatershedIdCardFigure",
        "comparison",
        (),
    ),
    "watertable_depth_map": (
        "hydromodpy.display.figures.watertable_depth_map.WatertableDepthMap",
        "spatial",
        ("watertable_depth",),
    ),
}


def test_the_registry_holds_exactly_the_figures_the_contract_declares() -> None:
    registered = set(names())

    assert registered, "the figure registry must not be empty"
    assert registered == set(REGISTRY_CONTRACT), (
        "registry and contract have drifted apart. "
        f"registered but undeclared: {sorted(registered - set(REGISTRY_CONTRACT))}; "
        f"declared but unregistered: {sorted(set(REGISTRY_CONTRACT) - registered)}"
    )


@pytest.mark.parametrize("name", sorted(REGISTRY_CONTRACT))
def test_a_registered_figure_matches_its_declared_contract(name: str) -> None:
    expected_class, expected_kind, expected_fields = REGISTRY_CONTRACT[name]

    assert name, "a figure must not register under an empty name"

    figure = get(name)
    cls = type(figure)
    actual_class = f"{cls.__module__}.{cls.__qualname__}"

    assert figure.spec.name == name, (
        f"figure registered as '{name}' answers to spec.name '{figure.spec.name}': "
        "the registry key and the figure's own name have drifted apart"
    )
    assert actual_class == expected_class
    assert figure.spec.kind == expected_kind
    assert tuple(figure.spec.required_fields or ()) == expected_fields
