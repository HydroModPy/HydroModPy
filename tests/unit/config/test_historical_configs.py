"""Real TOMLs of the published alphas are refused with every old key, or for a reason named here.

``corpus/<tag>/`` holds example files as the tags ``v2.0.0a1`` to ``v2.0.0a5`` wrote
them, comments removed, with their ``base_config`` parents and their data paths left as
they are. A key only a pre-release of 2.0 wrote is refused, so a file whose chain holds
one goes through ``hmp check`` and is refused with every such key of each of its
files, and the doctor of this version writes nothing on it. :data:`PRERELEASE_KEYS`
lists them, as ``prerelease_forms.txt`` named them once. A file with no such key is
refused only for a reason this table holds. Nothing here looks at a number.
"""

from __future__ import annotations

import shutil
import tomllib
import warnings
from fnmatch import fnmatch
from pathlib import Path

import pytest

from hydromodpy.config.config_migration import fix_config_chain
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.toml_io.paths import is_bare_filename
from hydromodpy.project.api import check

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted(path.relative_to(CORPUS) for path in CORPUS.rglob("*.toml"))

NO_SITE = "no [site] names it"
"""Only the author knows the catchment, so the doctor never writes ``[site]``. The test does."""

NO_REWRITE = "This version does not rewrite the file."
"""The sentence that ends the refusal of a key of a pre-release: no file is rewritten."""

PRERELEASE_KEYS: dict[str, tuple[str, ...]] = {
    "v2.0.0a1/01_calibration/project.toml": (
        "calibration.max_iter",
        "calibration.parameters.K_aquifer.transform",
        "flow.ic.type",
        "modflownwt.sgrid.vertical",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "modflownwt.sgrid.planar",
    ),
    "v2.0.0a1/04_streamflow_intermittence_in_transient/project.toml": (
        "calibration.protocol.scoring_window",
        "calibration.protocol.steady_engine_options",
        "calibration.protocol.steady_max_iter",
        "calibration.protocol.transient_max_iter",
        "calibration.protocol.steady_tolerance",
        "calibration.protocol.transient_tolerance",
        "display.overrides.seepage_map.timestep",
        "display.overrides.cross_section.timestep",
        "geographic.catchment.catch_def",
        "simulation.results.derived",
        "simulation.results.budget",
        "calibration.outputs.seepage_network.stream_geometry_path",
        "calibration.outputs.seepage_network.diagonal_neighbors",
        "calibration.rerun_best_with_outputs",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "flow.bc.drainage.kind",
        "simulation.if_exists",
    ),
    "v2.0.0a1/04_streamflow_intermittence_in_transient/run_calibration_by_hand.toml": (
        "calibration.phases[0].optimizer_kwargs",
        "calibration.phases[0].max_iter",
        "calibration.phases[1].max_iter",
        "calibration.phases[0].tolerance",
        "calibration.phases[1].tolerance",
        "calibration.objective_blocks[1].warmup",
        'calibration.phases[0].overrides."display.overrides.seepage_map.timestep"',
        'calibration.phases[0].overrides."display.overrides.cross_section.timestep"',
    ),
    "v2.0.0a1/04_streamflow_intermittence_in_transient/run_daily.toml": (
        "display.overrides.seepage_map.timestep",
        "display.overrides.cross_section.timestep",
    ),
    "v2.0.0a1/04_streamflow_intermittence_in_transient/step1_minimal.toml": (
        "geographic.catchment.catch_def",
        "flow.active_bc",
        "flow.active_sinks_sources",
    ),
    "v2.0.0a1/04_streamflow_intermittence_in_transient/step4_transient.toml": (
        "simulation.results.derived",
    ),
    "v2.0.0a1/04_streamflow_intermittence_in_transient/step5_export.toml": (
        "display.overrides.seepage_map.timestep",
        "export.geotiff",
        "export.csv_timeseries",
        "export.artifacts",
    ),
    "v2.0.0a1/05_nancon_data_overview/config_overview.toml": (
        "geographic.catchment.catch_def",
        "geographic.bottom_path",
    ),
    "v2.0.0a1/06_vire_selune/project_simulation.toml": (
        "flow.ic.type",
        "geographic.catchment.catch_def",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "flow.bc.drainage.kind",
    ),
    "v2.0.0a1/06_vire_selune/run_vire_mf6_irregular.toml": (
        "modflow6.sgrid.vertical",
        "flow.active_bc",
        "mesh_catchment",
    ),
    "v2.0.0a1/09_comparison_workflow/base_10km2_natural_mesh_fixed_heads.toml": (
        "flow.ic.type",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "mesh_input",
        "simulation.if_exists",
    ),
    "v2.0.0a1/20_atelier_nancon/calibration_discharge.toml": (
        "calibration.max_iter",
        "calibration.parameters.Sy.prior",
    ),
    "v2.0.0a1/20_atelier_nancon/project.toml": (
        "flow.ic.type",
        "geographic.catchment.catch_def",
        "display.output_dir",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "flow.bc.drainage.kind",
        "simulation.if_exists",
    ),
    "v2.0.0a1/21_nancon_network_calibration/auto_sfr_drn.toml": (
        "calibration.phases[1].scoring_window",
        "calibration.phases[0].optimizer_kwargs",
        "calibration.phases[1].optimizer_kwargs",
        "calibration.phases[0].max_iter",
        "calibration.phases[1].max_iter",
        "flow.ic.type",
        "geographic.catchment.catch_def",
        "simulation.results.derived",
        "calibration.outputs.seepage_network.roptim_max",
        "calibration.outputs.seepage_network.stream_geometry_path",
        "calibration.outputs.seepage_network.observed_position_accuracy",
        "calibration.outputs.seepage_network.tau_specific_ratio",
        "calibration.outputs.seepage_network.weighting",
        "display.output_dir",
        "calibration.rerun_best_with_outputs",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "flow.bc.drainage.kind",
        "simulation.if_exists",
        'calibration.phases[0].overrides."flow.active_bc"',
        'calibration.phases[1].overrides."flow.active_bc"',
    ),
    "v2.0.0a1/21_nancon_network_calibration/calibrated_best.toml": (
        "flow.ic.h.type",
        "geographic.catchment.catch_def",
        "solver.backend.backend",
        "modflow6.sgrid.vertical",
        "modflownwt.sgrid.vertical",
        "flow.runtime_backend",
        "flow.surface_interaction_model",
        "flow.vi_substeps_per_period",
        "flow.vi_substep_on_failure",
        "flow.ts_vi_steps_per_period",
        "flow.ts_vi_adapt",
        "flow.ts_vi_dt_min_fraction",
        "flow.ts_vi_dt_max_fraction",
        "flow.ts_vi_type",
        "flow.ts_vi_snes_type",
        "simulation.results.derived",
        "simulation.results.budget",
        "export.netcdf",
        "export.vtu",
        "export.geotiff",
        "export.shapefile",
        "export.csv_timeseries",
        "export.package",
        "export.artifacts",
        "workspace.catalog_path",
        "workspace.runs_dir",
        "display.output_dir",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "transport.param_list",
        "transport.param",
        "transport.bc",
        "transport.sinks_sources",
        "transport.active_sinks_sources",
        "transport.active_bc",
        "modflow6.sgrid.planar",
        "modflownwt.sgrid.planar",
        "modflow6.sgrid.grid_dual",
        "modflownwt.sgrid.grid_dual",
        "data.hydrography.sources[0].typename",
        "flow.bc.drainage.kind",
        "simulation.if_exists",
    ),
    "v2.0.0a1/21_nancon_network_calibration/ref_example04.toml": (
        "calibration.protocol.steady_engine_options",
        "calibration.protocol.transient_engine_options",
        "calibration.protocol.steady_max_iter",
        "flow.ic.type",
        "geographic.catchment.catch_def",
        "simulation.results.derived",
        "calibration.outputs.seepage_network.roptim_max",
        "calibration.outputs.seepage_network.stream_geometry_path",
        "calibration.outputs.seepage_network.observed_position_accuracy",
        "calibration.outputs.seepage_network.tau_specific_ratio",
        "calibration.outputs.seepage_network.diagonal_neighbors",
        "calibration.outputs.seepage_network.weighting",
        "display.output_dir",
        "calibration.rerun_best_with_outputs",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "simulation.if_exists",
    ),
    "v2.0.0a2/04_streamflow_intermittence_in_transient/project.toml": (
        "geographic.catchment.catch_def",
        "simulation.results.derived",
        "simulation.results.budget",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "simulation.if_exists",
    ),
    "v2.0.0a2/04_streamflow_intermittence_in_transient/run_calibration_bdtopage.toml": (
        "calibration.phases[0].scoring_window",
        "calibration.phases[1].scoring_window",
        "calibration.phases[1].max_iter",
        "calibration.phases[1].tolerance",
        "calibration.outputs.seepage_network.extent.maximal_flowing_steps",
        "calibration.outputs.seepage_network.extent.minimal_dry_steps",
        "calibration.outputs.seepage_network.observed_network",
        "calibration.outputs.seepage_network.minimal_observed_network",
        "calibration.outputs.seepage_network.extent",
        "calibration.outputs.seepage_network.extent.weights",
        "calibration.rerun_best_with_outputs",
    ),
    "v2.0.0a2/04_streamflow_intermittence_in_transient/step1_minimal.toml": (
        "geographic.catchment.catch_def",
        "flow.active_bc",
        "flow.active_sinks_sources",
    ),
    "v2.0.0a2/04_streamflow_intermittence_in_transient/step2_local_data.toml": (
        "simulation.results.derived",
    ),
    "v2.0.0a3/04_streamflow_intermittence_in_transient/project.toml": (
        "geographic.catchment.catch_def",
        "simulation.results.derived",
        "simulation.results.budget",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "simulation.if_exists",
    ),
    "v2.0.0a3/04_streamflow_intermittence_in_transient/step1_minimal.toml": (
        "geographic.catchment.catch_def",
        "flow.active_bc",
        "flow.active_sinks_sources",
    ),
    "v2.0.0a3/04_streamflow_intermittence_in_transient/step2_local_data.toml": (
        "simulation.results.derived",
    ),
    "v2.0.0a4/04_streamflow_intermittence_in_transient/project.toml": (
        "geographic.catchment.catch_def",
        "simulation.results.derived",
        "simulation.results.budget",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "simulation.if_exists",
    ),
    "v2.0.0a4/04_streamflow_intermittence_in_transient/step1_minimal.toml": (
        "geographic.catchment.catch_def",
        "flow.active_bc",
        "flow.active_sinks_sources",
    ),
    "v2.0.0a4/04_streamflow_intermittence_in_transient/step2_local_data.toml": (
        "simulation.results.derived",
        "simulation.results.budget",
    ),
    "v2.0.0a5/04_streamflow_intermittence_in_transient/project.toml": (
        "geographic.catchment.catch_def",
        "flow.active_bc",
        "flow.active_sinks_sources",
        "simulation.if_exists",
    ),
    "v2.0.0a5/04_streamflow_intermittence_in_transient/step1_minimal.toml": (
        "geographic.catchment.catch_def",
        "flow.active_bc",
        "flow.active_sinks_sources",
    ),
    "v2.0.0a5/04_streamflow_intermittence_in_transient/step6_soil_reservoir.toml": (
        "flow.ic.type",
        "flow.active_sinks_sources",
    ),
}
"""The keys only a pre-release wrote in each file of the corpus that holds one, in the order
of the refusal."""

REASONS = {
    "a comparison is a set of recipes": "workflow.mode = 'comparison' is gone",
}

EXPECTED = (("*/09_*/compare_*", "a comparison is a set of recipes"),)
"""What a file with no key of a pre-release gives: the first pattern that matches says it."""


def _expected_reason(relative: Path) -> str | None:
    return next((reason for pattern, reason in EXPECTED if fnmatch(str(relative), pattern)), None)


def _chain(relative: Path) -> list[Path]:
    """Return *relative* and the files it inherits through ``base_config``, parents first."""
    chain = [relative]
    while True:
        document = tomllib.loads((CORPUS / chain[0]).read_text(encoding="utf-8-sig"))
        parent = document.get("base_config")
        if parent is None:
            return chain
        chain.insert(0, chain[0].parent / parent)


def _held_by_the_chain(relative: Path) -> dict[Path, tuple[str, ...]]:
    """Return each file of the chain of *relative* that holds a key of a pre-release."""
    return {
        file: PRERELEASE_KEYS[str(file)]
        for file in _chain(relative)
        if str(file) in PRERELEASE_KEYS
    }


OF_A_PRE_RELEASE = [relative for relative in FILES if _held_by_the_chain(relative)]


PATH_KEYS = ("path", "dem_init_path", "mask_path", "complete")
"""The keys that name a file the loader looks for."""


def _bare_names(node: object) -> set[str]:
    """Return the bare file names a parsed document writes under a key of :data:`PATH_KEYS`."""
    if isinstance(node, dict):
        found = {
            value
            for key, value in node.items()
            if key in PATH_KEYS and isinstance(value, str) and is_bare_filename(value)
        }
        return found.union(*(_bare_names(value) for value in node.values()))
    if isinstance(node, list):
        return set().union(*(_bare_names(item) for item in node))
    return set()


def _copy_of(relative: Path, tmp_path: Path, *, with_the_data: bool = True) -> Path:
    """Copy the example of *relative* aside, so nothing rewrites the corpus.

    A bare file name is refused unless the file is at the project root, and the corpus
    holds no data. With *with_the_data* an empty file stands at the root for each bare
    name, so a file is judged on the other reasons of this table.
    """
    example = Path(*relative.parts[:2])
    shutil.copytree(CORPUS / example, tmp_path / example)
    if with_the_data:
        for file in (tmp_path / example).rglob("*.toml"):
            document = tomllib.loads(file.read_text(encoding="utf-8-sig"))
            for name in _bare_names(document):
                (file.parent / name).touch()
    return tmp_path / relative


def _error_text(path: Path) -> str:
    """Return the errors of the check of *path* as ``key: detail`` texts, a key to fill included."""
    return " ".join(
        f"{item.path}: {item.detail}"
        for item in check(path, partial=False)
        if item.severity == "error"
    )


def _errors_of(path: Path) -> str:
    """Return what ``hmp check`` refuses in *path*, with ``[site]`` added when it asks."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        errors = _error_text(path)
        if NO_SITE in errors:
            child = path.with_name(f"with_a_site_{path.name}")
            child.write_text(
                f'base_config = "{path.name}"\n[site]\nname = "corpus"\n', encoding="utf-8"
            )
            errors = _error_text(child)
    return errors


def test_the_corpus_is_found_and_every_reason_serves() -> None:
    assert len(FILES) >= 50
    assert set(PRERELEASE_KEYS) <= {str(relative) for relative in FILES}
    assert len(OF_A_PRE_RELEASE) == 48
    others = [relative for relative in FILES if relative not in OF_A_PRE_RELEASE]
    assert {_expected_reason(relative) for relative in others} - {None} == set(REASONS)


@pytest.mark.parametrize("relative", OF_A_PRE_RELEASE, ids=str)
def test_a_file_of_a_pre_release_is_refused_with_every_key_of_its_chain(
    relative: Path, tmp_path: Path
) -> None:
    """The loader of a run names each file of the chain with the keys it holds."""
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ConfigError) as refused:
            HydroModPyConfig.from_toml(_copy_of(relative, tmp_path))

    told = str(refused.value)
    assert told.count(NO_REWRITE) == len(_held_by_the_chain(relative)), told
    for file, keys in _held_by_the_chain(relative).items():
        assert f"{tmp_path / file} holds {', '.join(keys)}, written by a pre-release" in told


@pytest.mark.parametrize("relative", OF_A_PRE_RELEASE, ids=str)
def test_the_doctor_refuses_a_file_of_a_pre_release_and_writes_nothing(
    relative: Path, tmp_path: Path
) -> None:
    target = _copy_of(relative, tmp_path)
    files = sorted(target.parent.glob("*.toml"))
    written = [file.read_text(encoding="utf-8-sig") for file in files]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ConfigError) as refused:
            fix_config_chain(target)

    assert [file.read_text(encoding="utf-8-sig") for file in files] == written
    told = str(refused.value)
    assert NO_REWRITE in told
    for file, keys in _held_by_the_chain(relative).items():
        assert f"{tmp_path / file} holds {', '.join(keys)}, written by a pre-release" in told


@pytest.mark.parametrize(
    "relative", [relative for relative in FILES if relative not in OF_A_PRE_RELEASE], ids=str
)
def test_a_file_with_no_key_of_a_pre_release_is_refused_only_for_its_named_reason(
    relative: Path, tmp_path: Path
) -> None:
    reason = _expected_reason(relative)

    errors = _errors_of(_copy_of(relative, tmp_path))

    if reason is None:
        assert not errors
    else:
        assert REASONS[reason] in errors, errors
        assert NO_REWRITE not in errors
