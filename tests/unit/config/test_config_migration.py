"""Tests for the one-shot ``hmp doctor --fix-config`` TOML rewriter."""

from __future__ import annotations

import copy
import importlib
import tomllib
import warnings
from pathlib import Path

import pytest
import tomlkit
from packaging.version import Version

from hydromodpy.calibration.config import validate_calib_output
from hydromodpy.config.config_migration import (
    ALPHA_FORM,
    DEPRECATION_DELAY_MINORS,
    MOVED_TABLES,
    OLD_VALUES,
    RENAMED_KEYS,
    OldForm,
    _value_at,
    document_path,
    fix_config_chain,
    fix_config_file,
    migrate_config_doc,
    migrate_config_doc_on_load,
    migrate_merged_doc,
    migrate_sealed_config_doc,
    old_forms,
    outlived_forms,
    rewrite_dotted_path,
)
from hydromodpy.core.config_kit.base import (
    CANNOT_REWRITE,
    ConfigKeyRenamedWarning,
    HydroModelBase,
    forget_old_forms_told,
    warn_old_form,
)
from hydromodpy.core.exceptions import ConfigError, ConfigValidationError
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.core.version import __version__
from tools.surface_snapshot import outlived_interface_forms, toml_fields


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "project.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_migrates_on_collision_and_run_id(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "# header\n[simulation]\n# the run name\n"
        'run_id = "cheze_baseline"\non_collision = "replace"\n'
        'description = "weekly"\n',
    )
    changes = fix_config_file(path)
    assert any("on_collision -> if_exists" in c for c in changes)
    assert any("run_id -> name" in c for c in changes)

    parsed = tomllib.loads(path.read_text())["simulation"]
    assert "on_collision" not in parsed
    assert parsed["if_exists"] == "version"
    assert "run_id" not in parsed
    assert parsed["name"] == "cheze_baseline"
    # comments and untouched keys survive the round-trip
    text = path.read_text()
    assert "# header" in text
    assert parsed["description"] == "weekly"


def test_run_id_dropped_when_name_already_set(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[simulation]\nname = "kept"\nrun_id = "ignored"\n',
    )
    changes = fix_config_file(path)
    assert any("name already set" in c for c in changes)
    parsed = tomllib.loads(path.read_text())["simulation"]
    assert parsed["name"] == "kept"
    assert "run_id" not in parsed


def test_idempotent_and_noop_returns_empty(tmp_path: Path) -> None:
    path = _write(tmp_path, '[simulation]\nname = "modern"\nif_exists = "version"\n')
    assert fix_config_file(path) == []


def test_promotes_export_to_top_level(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[simulation]\nname = "cheze"\n\n'
        "[simulation.results.export]\ncsv_timeseries = true\ngeotiff = true\n\n"
        '[[simulation.results.export.artifacts]]\nvar = "head"\ndest = "h.tif"\n',
    )
    changes = fix_config_file(path)
    assert any("simulation.results.export -> [export]" in c for c in changes)

    parsed = tomllib.loads(path.read_text())
    assert parsed["export"] == [
        {"variables": "all", "format": "csv"},
        {"variables": ["head"], "format": "geotiff", "time": "last"},
        {"variables": "head", "file": "h.tif"},
    ]
    # the buried section is gone
    assert "export" not in parsed.get("simulation", {}).get("results", {})


def test_export_promotion_skips_when_top_level_exists(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "[export]\nnetcdf = true\n\n[simulation.results.export]\ncsv_timeseries = false\n",
    )
    changes = fix_config_file(path)
    assert any("top-level [export] already set" in c for c in changes)
    parsed = tomllib.loads(path.read_text())
    assert parsed["export"] == [{"variables": ["head"], "format": "netcdf", "time": "last"}]
    assert "export" not in parsed.get("simulation", {}).get("results", {})


def test_drops_the_two_options_that_never_drove_anything(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[simulation]\nname = "cheze"\n\n'
        '[simulation.results]\nsolver_scratch = ".hmp/scratch"\nkeep_solver_files = true\n\n'
        "[simulation.results.persistence]\nsave_lock = true\nsave_zarr = true\n\n"
        "[persistence]\nsave_lock = false\n",
    )
    changes = fix_config_file(path)
    assert any("solver_scratch dropped" in c for c in changes)
    assert sum("save_lock dropped" in c for c in changes) == 2

    parsed = tomllib.loads(path.read_text())
    results = parsed["simulation"]["results"]
    assert "solver_scratch" not in results
    assert results["keep_solver_files"] is True
    assert "save_lock" not in results["persistence"]
    assert results["persistence"]["save_zarr"] is True
    assert "save_lock" not in parsed["persistence"]
    assert fix_config_file(path) == []


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fix_config_file(tmp_path / "absent.toml")


def test_flattens_a_family_keyed_boundary(tmp_path: Path) -> None:
    """``[flow.bc.<family>.<id>]`` becomes ``[flow.bc.<id>]`` carrying its kind."""
    path = _write(
        tmp_path,
        "[flow.bc.dirichlet.west_side]\nvalue = 5.0\n\n"
        '[flow.bc.cauchy.drainage]\nvalue = "1e-6 m2/s"\n',
    )

    changes = fix_config_file(path)
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    bc = parsed["flow"]["bc"]

    assert "dirichlet" not in bc
    assert "cauchy" not in bc
    assert bc["west_side"] == {"value": 5.0, "kind": "dirichlet"}
    assert bc["drainage"] == {"value": "1e-6 m2/s", "kind": "drain"}
    assert len(changes) == 3
    assert fix_config_file(path) == []


def test_a_flat_entry_already_there_wins_over_the_nested_one(tmp_path: Path) -> None:
    """A flat mapping cannot hold the same id twice, so the nested one is dropped."""
    path = _write(
        tmp_path,
        "[flow.bc.west_side]\nvalue = 9.0\n\n[flow.bc.dirichlet.west_side]\nvalue = 1.0\n",
    )

    changes = fix_config_file(path)
    bc = tomllib.loads(path.read_text(encoding="utf-8"))["flow"]["bc"]

    assert bc["west_side"] == {"value": 9.0}
    assert "dirichlet" not in bc
    assert changes == ["flow.bc.dirichlet.west_side dropped (flow.bc.west_side already set)"]


def test_a_file_with_no_flow_section_is_left_alone(tmp_path: Path) -> None:
    path = _write(tmp_path, '[simulation]\nname = "plain"\n')
    assert fix_config_file(path) == []


def test_drops_both_solver_time_grids_at_the_root(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "[modflow6]\nrelax_steady = true\n\n[modflow6.tgrid]\nnper = 1\n\n"
        '[modflownwt]\n\n[modflownwt.tgrid]\nitmuni = "days"\nnper = 1\n',
    )

    changes = fix_config_file(path)

    assert any("modflow6.tgrid dropped" in c for c in changes)
    assert any("modflownwt.tgrid dropped" in c for c in changes)
    parsed = tomllib.loads(path.read_text())
    assert "tgrid" not in parsed["modflow6"]
    assert "tgrid" not in parsed["modflownwt"]
    assert parsed["modflow6"]["relax_steady"] is True


def test_migrates_a_config_carrying_a_byte_order_mark(tmp_path: Path) -> None:
    """tomlkit reads a BOM as an empty key, which used to abort the whole fix."""
    path = tmp_path / "project.toml"
    path.write_text("\ufeff[modflownwt.tgrid]\nnper = 1\n", encoding="utf-8")

    changes = fix_config_file(path)

    assert any("modflownwt.tgrid dropped" in c for c in changes)
    assert tomllib.loads(path.read_text()) == {}


def test_expands_the_export_variables_boolean_table(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "[export]\ngeotiff = true\n[export.variables]\nhead = true\nconcentration = false\n"
        "derived = true\nbudget = true\npathlines = true\n",
    )
    changes = fix_config_file(path)
    assert any("export.variables (boolean table) -> list" in c for c in changes)

    (block,) = tomllib.loads(path.read_text())["export"]
    assert block["variables"] == [
        "head",
        "watertable_elevation",
        "watertable_depth",
        "seepage_mask",
    ]
    assert fix_config_file(path) == []


def test_export_variables_all_off_is_carried_as_an_empty_list(tmp_path: Path) -> None:
    """The request keeps what the file said; the loader then refuses an empty list."""
    path = _write(
        tmp_path,
        "[export]\nnetcdf = true\n[export.variables]\nhead = false\nconcentration = false\n",
    )
    changes = fix_config_file(path)
    assert any("-> list []" in c for c in changes)
    assert tomllib.loads(path.read_text())["export"][0]["variables"] == []


def test_renames_export_times_to_time(tmp_path: Path) -> None:
    path = _write(tmp_path, '[export]\ngeotiff = true\ntimes = "first"\n')
    changes = fix_config_file(path)
    assert any("export.times -> export.time" in c for c in changes)

    (block,) = tomllib.loads(path.read_text())["export"]
    assert block["time"] == "first"
    assert "times" not in block
    assert fix_config_file(path) == []


def test_export_times_dropped_when_time_already_set(tmp_path: Path) -> None:
    path = _write(tmp_path, '[export]\nnetcdf = true\ntime = "all"\ntimes = "last"\n')
    changes = fix_config_file(path)
    assert any("export.time already set" in c for c in changes)
    (block,) = tomllib.loads(path.read_text())["export"]
    # "all" is the default of a request: the whole simulation.
    assert block == {"variables": ["head"], "format": "netcdf"}


def test_each_format_toggle_becomes_one_request_in_the_order_it_ran() -> None:
    """The export and the artifact of example 04 step 5, before the reshape."""
    doc = tomllib.loads(
        "[export]\ngeotiff = true\ncsv_timeseries = true\ntime = 33\nresolution = 50.0\n"
        'variables = ["head", "watertable_depth"]\npackage = true\noutput_dir = "deliver"\n\n'
        '[[export.artifacts]]\nvar = ["head", "watertable_depth"]\ndest = "fields.nc"\n'
        'time = "all"\n\n'
        '[[export.artifacts]]\nvar = "*"\nfmt = "csv"\ndest = "series.csv"\n\n'
        '[[export.artifacts]]\nvar = "head"\nfmt = "hmp"\ndest = "run.hmp"\n'
    )

    changes = migrate_config_doc(doc)

    assert doc["export"] == [
        {"variables": "all", "format": "csv", "folder": "deliver"},
        {
            "variables": ["head", "watertable_depth"],
            "format": "geotiff",
            "resolution": 50.0,
            "time": 33,
            "folder": "deliver",
        },
        {"variables": ["head", "watertable_depth"], "file": "fields.nc", "folder": "deliver"},
        {"variables": "all", "format": "csv", "file": "series.csv", "folder": "deliver"},
    ]
    # The archive (package = true, fmt = "hmp") is not an export: hmp publish writes it.
    assert len(changes) == 2
    assert changes[0].startswith("[export] archive request(s) dropped")
    assert "hmp publish --container tar" in changes[0]
    assert changes[1] == (
        "[export] toggles and artifacts -> 4 [[export]] block(s) (csv, geotiff, by extension, csv)"
    )


def test_the_requests_of_a_migrated_table_load(tmp_path: Path) -> None:
    """What the migration writes is what the model reads: the round trip holds."""
    from hydromodpy.core.config_kit.export_spec import ExportFormat, load_export_requests

    path = _write(
        tmp_path,
        "[export]\ngeotiff = true\ncsv_timeseries = true\ntime = 33\n"
        'variables = ["head", "watertable_depth"]\n\n'
        '[[export.artifacts]]\nvar = ["head", "watertable_depth"]\ndest = "fields.nc"\n'
        'time = "all"\n',
    )
    fix_config_file(path)

    requests = load_export_requests(tomllib.loads(path.read_text())["export"])

    assert [request.output_format for request in requests] == [
        ExportFormat.csv,
        ExportFormat.geotiff,
        ExportFormat.netcdf,
    ]
    assert requests[1].time == 33


def test_an_archive_artifact_is_dropped_and_names_hmp_publish() -> None:
    """No export writes the archive of a run: the artifacts asking for it are dropped."""
    doc = tomllib.loads(
        "[export]\n\n"
        '[[export.artifacts]]\nvar = "head"\nfmt = "hmp"\ndest = "run.hmp"\ntime = 3\n\n'
        '[[export.artifacts]]\nvar = ["head"]\ndest = "copy.hmp"\ncrs = "EPSG:4326"\n'
        "resolution = 25.0\n"
    )

    changes = migrate_config_doc(doc)

    assert "export" not in doc
    assert len(changes) == 2 and "hmp publish --container tar" in changes[0]
    # One archive beside a real export: the export stays, the archive goes.
    doc = tomllib.loads(
        "[export]\nnetcdf = true\npackage = true\n\n"
        '[[export.artifacts]]\nvar = "*"\nfmt = "csv"\ndest = "series.csv"\n'
    )
    changes = migrate_config_doc(doc)
    assert doc["export"] == [
        {"variables": ["head"], "format": "netcdf", "time": "last"},
        {"variables": "all", "format": "csv", "file": "series.csv"},
    ]
    assert changes[0].startswith("[export] archive request(s) dropped")


def test_a_table_with_every_format_off_is_dropped_without_a_word(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The resolved config every sealed run holds: `hmp run --resume` replays it."""
    body = (
        "[export]\nnetcdf = false\ncsv_timeseries = false\nvtu = false\ngeotiff = false\n"
        'shapefile = false\ngeopackage = false\npackage = false\nvariables = ["head"]\n'
        'time = "last"\nartifacts = []\n'
    )
    doc = tomllib.loads(body)
    with caplog.at_level("INFO", logger="hydromodpy"):
        changes = migrate_config_doc_on_load(doc, source="runs/x/config.toml")

    assert "export" not in doc
    assert len(changes) == 1
    assert [record for record in caplog.records if record.levelname == "INFO"] == []

    path = _write(tmp_path, body)
    assert fix_config_file(path) == changes
    assert "export" not in tomllib.loads(path.read_text())


def test_a_request_written_as_a_table_is_left_for_the_loader_to_refuse() -> None:
    doc = tomllib.loads('[export]\nvariables = "head"\nformat = "netcdf"\n')

    assert migrate_config_doc(doc) == []
    assert doc["export"] == {"variables": "head", "format": "netcdf"}


def test_an_array_of_requests_is_current() -> None:
    doc = tomllib.loads('[[export]]\nvariables = "head"\ntime = "2002-10-15"\n')

    assert migrate_config_doc(doc) == []


def test_migrate_config_doc_on_load_leaves_a_current_doc_untouched(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc = tomllib.loads('[simulation]\nname = "cheze"\nif_exists = "version"\n')
    with caplog.at_level("INFO"):
        changes = migrate_config_doc_on_load(doc, source="cheze.toml")
    assert changes == []
    assert caplog.records == []


OLD_EXPORT = '[export]\ngeotiff = true\ntimes = "last"\n[export.variables]\nhead = true\n'


def test_a_load_migrates_in_memory_and_warns_once_per_key_and_file(tmp_path: Path) -> None:
    source = tmp_path / "project.toml"
    doc = tomllib.loads(OLD_EXPORT)
    with pytest.warns(ConfigKeyRenamedWarning) as told:
        changes = migrate_config_doc_on_load(doc, source=source)

    assert changes == [
        "export.times -> export.time ('last')",
        "export.variables (boolean table) -> list ['head']",
        "[export] toggles and artifacts -> 1 [[export]] block(s) (geotiff)",
    ]
    assert doc["export"] == [{"variables": ["head"], "format": "geotiff", "time": "last"}]
    assert len(told) == len(changes)
    for change, warning in zip(changes, told, strict=True):
        assert change in str(warning.message)
        assert f"hmp doctor --fix-config {source}" in str(warning.message)

    with warnings.catch_warnings():
        warnings.simplefilter("error", ConfigKeyRenamedWarning)
        assert migrate_config_doc_on_load(tomllib.loads(OLD_EXPORT), source=source) == changes

    with pytest.warns(ConfigKeyRenamedWarning):
        migrate_config_doc_on_load(tomllib.loads(OLD_EXPORT), source=tmp_path / "other.toml")


def test_a_report_on_a_file_sees_its_old_forms_again(tmp_path: Path) -> None:
    source = tmp_path / "project.toml"
    with pytest.warns(ConfigKeyRenamedWarning):
        migrate_config_doc_on_load(tomllib.loads(OLD_EXPORT), source=source)

    forget_old_forms_told()

    with pytest.warns(ConfigKeyRenamedWarning):
        migrate_config_doc_on_load(tomllib.loads(OLD_EXPORT), source=source)


def test_a_form_the_loader_cannot_rewrite_does_not_promise_the_doctor() -> None:
    with pytest.warns(ConfigKeyRenamedWarning, match="seed left: why") as told:
        warn_old_form("project.toml", "calibration.seed left: why")
    assert "hmp doctor" not in str(told[0].message)


def test_the_delay_is_two_minor_versions_the_one_that_retired_the_form_included() -> None:
    form = OldForm("a.old", "a.new", "2.3.0")

    assert DEPRECATION_DELAY_MINORS == 2
    assert form.removal == "2.5.0"
    assert not form.outlived_by("2.4.9")
    assert form.outlived_by("2.5.0a1")
    assert form.outlived_by("3.0.0")
    assert not OldForm("a.old", None, "2.0.0").outlived_by("2.1.0rc1")


def test_no_old_form_outlives_its_delay() -> None:
    forms = (*outlived_forms(__version__), *outlived_interface_forms(__version__))
    late = [f"{form.old} (since {form.since})" for form in forms]
    assert late == [], (
        f"HydroModPy {__version__} still holds old forms past their delay: {late}. Delete each "
        "one from hydromodpy/config/config_migration.py, OLD_NAMES in hydromodpy/_lazy.py or "
        "OLD_CLI_FORMS in hydromodpy/cli/conventions.py. A row of RENAMED_KEYS stays with "
        "sealed_only=True, because a run sealed under the old name stays readable."
    )


def test_every_form_states_a_version_and_is_listed_once() -> None:
    forms = old_forms()
    assert all(Version(form.since) >= Version(ALPHA_FORM) for form in forms)
    paths = [(form.old, form.new) for form in forms]
    assert len(paths) == len(set(paths))


def _config_models() -> list[type]:
    importlib.import_module("hydromodpy.config.hydromodpy_config")
    found, todo = [], [HydroModelBase]
    while todo:
        cls = todo.pop()
        # A test may define its own model, and it stays a subclass for the whole session.
        if cls.__module__.startswith("hydromodpy."):
            found.append(cls)
        todo.extend(cls.__subclasses__())
    return found


def test_every_rename_a_model_declares_has_its_form() -> None:
    """``renamed_from``, ``model_legacy_keys`` and ``model_retired_keys`` all name an old form."""
    known = {document_path(form.old) for form in old_forms()}
    leaves = {path.rsplit(".", 1)[-1] for path in known}
    declared: set[str] = set()
    for model in _config_models():
        for field in model.model_fields.values():
            extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
            declared.update(extra.get("renamed_from") or ())
    assert declared
    assert sorted(declared - known) == []
    # A model knows the leaf of its key and not the path that reaches it.
    for model in _config_models():
        undeclared = (set(model.model_legacy_keys) | set(model.model_retired_keys)) - leaves
        assert undeclared == set(), f"{model.__name__} retires {undeclared} with no old form"


def test_a_refusal_at_load_names_every_old_calibration_key_of_the_file(tmp_path: Path) -> None:
    source = tmp_path / "project.toml"
    doc = {"calibration": {"optimizer_kwargs": {"seed": 1}, "max_iter": 5}}

    with pytest.raises(ConfigValidationError) as refused:
        migrate_config_doc_on_load(doc, source=source)

    assert str(refused.value) == (
        f"{source}: calibration.optimizer_kwargs -> method_options; "
        "calibration.max_iter -> max_trials. This old form is refused; "
        f"`hmp doctor --fix-config {source}` rewrites the file."
    )


_FROZEN_V1 = Path(__file__).parent / "fixtures" / "frozen_run_config_export_v1.toml"


def test_frozen_export_config_from_example_04_migrates_and_loads() -> None:
    """Regression test for the frozen run config this migration exists for.

    A resolved ``runs/<name>/config.toml`` of example 04 written before the
    reshape holds the ``[export.variables]`` boolean table, ``export.times``
    and every format off. ``migrate_config_doc`` carries it across in one
    pass, on the plain dict ``tomllib`` hands back, without writing to disk.
    """
    original_bytes = _FROZEN_V1.read_bytes()
    doc = tomllib.loads(original_bytes.decode("utf-8"))

    changes = migrate_config_doc(doc)

    # Every format was off: the run wrote nothing, and the migration says so once.
    assert "export" not in doc
    assert changes == ["[export] dropped: every format was off, so it wrote nothing"]
    assert doc["simulation"]["name"] == "nancon_intermittence_mf6"
    # migrate_config_doc mutates the in-memory payload only, never the file
    assert _FROZEN_V1.read_bytes() == original_bytes


def test_renames_a_figure_timestep_to_time(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[display]\nfigures = ["seepage_map"]\n\n'
        "[display.overrides.seepage_map]\ntimestep = 33 # October 2002\n\n"
        '[display.overrides.cross_section]\norientation = "sn"\n',
    )

    changes = fix_config_file(path)

    assert changes == ["display.overrides.seepage_map.timestep -> time"]
    overrides = tomllib.loads(path.read_text())["display"]["overrides"]
    assert overrides == {"seepage_map": {"time": 33}, "cross_section": {"orientation": "sn"}}
    assert fix_config_file(path) == []


def test_a_figure_that_says_both_is_left_for_the_loader_to_refuse() -> None:
    """Both spellings may name different instants: picking one would hide it."""
    doc = {"display": {"overrides": {"seepage_map": {"timestep": 33, "time": "2002-10-15"}}}}
    phase = {"display.overrides.seepage_map.timestep": 0, "display.overrides.seepage_map.time": 1}
    doc["calibration"] = {"phases": [{"overrides": dict(phase)}]}

    assert all(" left: " in change for change in migrate_config_doc(doc))
    assert doc["display"]["overrides"]["seepage_map"] == {"timestep": 33, "time": "2002-10-15"}
    assert doc["calibration"]["phases"][0]["overrides"] == phase


def test_renames_the_dotted_timestep_a_calibration_phase_overrides(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[[calibration.phases]]\nname = "steady"\n\n'
        "[calibration.phases.overrides]\n"
        '"display.overrides.seepage_map.timestep" = 0\n'
        '"display.overrides.cross_section.timestep" = 0\n'
        '"flow.flow_regime" = "steady"\n',
    )

    changes = fix_config_file(path)

    assert changes == [
        'calibration.phases[0].overrides."display.overrides.seepage_map.timestep" -> '
        '"display.overrides.seepage_map.time"',
        'calibration.phases[0].overrides."display.overrides.cross_section.timestep" -> '
        '"display.overrides.cross_section.time"',
    ]
    overrides = tomllib.loads(path.read_text())["calibration"]["phases"][0]["overrides"]
    assert overrides == {
        "flow.flow_regime": "steady",
        "display.overrides.seepage_map.time": 0,
        "display.overrides.cross_section.time": 0,
    }


def test_renames_a_phase_timestep_written_as_nested_tables() -> None:
    doc = {
        "calibration": {
            "phases": [{"overrides": {"display": {"overrides": {"seepage_map": {"timestep": 0}}}}}]
        }
    }

    changes = migrate_config_doc(doc)

    phase = doc["calibration"]["phases"][0]
    assert phase["overrides"]["display"]["overrides"]["seepage_map"] == {"time": 0}
    assert len(changes) == 1


def test_moves_the_bottom_path_to_the_substratum_and_leaves_the_depth_model(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        '[geographic]\nbottom_path = "data/bottom.tif"\n\n'
        '[domain.depth_model]\nkind = "constant_thickness"\nthickness = "30 m"\n',
    )

    changes = fix_config_file(path)

    assert any("geographic.bottom_path -> [[data.substratum.sources]]" in c for c in changes)
    parsed = tomllib.loads(path.read_text())
    assert "bottom_path" not in parsed["geographic"]
    assert parsed["data"]["substratum"]["sources"] == [
        {"source": "custom", "path": "data/bottom.tif"}
    ]
    # The key was never read: switching the kind would change the results.
    assert parsed["domain"]["depth_model"] == {"kind": "constant_thickness", "thickness": "30 m"}


def test_bottom_path_dropped_when_a_substratum_is_already_declared() -> None:
    doc = {
        "geographic": {"bottom_path": "old.tif"},
        "data": {"substratum": {"sources": [{"source": "custom", "path": "new.tif"}]}},
    }

    changes = migrate_config_doc(doc)

    assert changes == ["geographic.bottom_path dropped ([data.substratum] already set)"]
    assert doc["data"]["substratum"]["sources"][0]["path"] == "new.tif"
    assert "bottom_path" not in doc["geographic"]


_NETWORK_OUTPUT = (
    "[calibration.outputs.seepage_network]\n"
    'support = "network"\n'
    'stream_geometry_path = "streams.gpkg"\n'
    "# the paper's bound\n"
    "roptim_max = {value}\n"
    'observed_position_accuracy = "50 m"\n'
)


def test_the_paper_ratio_bound_is_dropped_and_auto_replaces_it(tmp_path: Path) -> None:
    from hydromodpy.calibration.config import validate_calib_output

    path = _write(tmp_path, _NETWORK_OUTPUT.format(value="2.0"))

    changes = fix_config_file(path)

    assert changes[0] == (
        "calibration.outputs.seepage_network.roptim_max dropped "
        "(2 cells is validity_length = 'auto', the default)"
    )
    output = tomllib.loads(path.read_text())["calibration"]["outputs"]["seepage_network"]
    assert "roptim_max" not in output
    assert output["map"]["position_accuracy"] == "50 m"
    assert validate_calib_output(output).verdict.validity_length == "auto"


def test_an_integer_two_is_the_paper_bound_too() -> None:
    doc = {"calibration": {"outputs": {"net": {"support": "network", "roptim_max": 2}}}}

    assert len(migrate_config_doc(doc)) == 1
    assert "roptim_max" not in doc["calibration"]["outputs"]["net"]


def test_another_ratio_bound_is_refused_with_the_length_to_write(tmp_path: Path) -> None:
    path = _write(tmp_path, _NETWORK_OUTPUT.format(value="3.0"))
    before = path.read_bytes()

    with pytest.raises(ValueError, match="validity_length") as raised:
        fix_config_file(path)

    assert "roptim_max = 3 has no exact equivalent" in str(raised.value)
    assert path.read_bytes() == before


def test_a_sealed_run_drops_any_ratio_bound_and_says_so(tmp_path: Path) -> None:
    doc = {"calibration": {"outputs": {"net": {"support": "network", "roptim_max": 3.0}}}}
    sealed = tmp_path / "runs" / "nancon" / "config.toml"

    changes = migrate_merged_doc(doc, [(sealed, doc)])

    assert changes == ["calibration.outputs.net.roptim_max dropped (sealed)"]
    assert doc["calibration"]["outputs"]["net"] == {"support": "network"}


def test_the_ratio_bound_migrates_on_load_and_a_current_file_is_untouched() -> None:
    doc = {"calibration": {"outputs": {"net": {"support": "network", "roptim_max": 2.0}}}}
    current = {"calibration": {"outputs": {"net": {"validity_length": "150 m"}}}}

    assert migrate_config_doc(doc)
    assert migrate_config_doc(current) == []
    assert current["calibration"]["outputs"]["net"] == {"validity_length": "150 m"}


def _chain(tmp_path: Path, parent: str, child: str) -> tuple[Path, Path]:
    """Write a parent and a child that inherits it; return both paths."""
    first = tmp_path / "parent.toml"
    first.write_text(parent, encoding="utf-8")
    second = tmp_path / "child.toml"
    second.write_text(f'base_config = "parent.toml"\n{child}', encoding="utf-8")
    return first, second


def test_the_doctor_follows_the_chain_and_rewrites_each_file_that_holds_an_old_form(
    tmp_path: Path,
) -> None:
    parent, child = _chain(
        tmp_path,
        '# the project\n[simulation]\non_collision = "version" # keep every run\n',
        "# one run\n[calibration]\nmax_iter = 5 # short\n",
    )

    changes = fix_config_chain(child)

    assert changes == {
        parent: ["simulation.on_collision -> if_exists ('version')"],
        child: ["calibration.max_iter -> max_trials"],
    }
    assert "# the project" in parent.read_text()
    assert "# one run" in child.read_text()
    assert "# short" in child.read_text()
    assert tomllib.loads(parent.read_text())["simulation"] == {"if_exists": "version"}
    assert tomllib.loads(child.read_text())["calibration"] == {"max_trials": 5}
    assert fix_config_chain(child) == {parent: [], child: []}
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConfigKeyRenamedWarning)
        load_toml_with_base_config(child)


@pytest.mark.parametrize(
    ("parent", "said"),
    [
        pytest.param(
            '[simulation]\non_collision = "version"\n',
            "simulation.on_collision -> if_exists",
            id="a key one file can move",
        ),
        pytest.param(
            '[export]\nnetcdf = true\nvariables = ["head"]\n',
            "[export] toggles and artifacts",
            id="a table that waits for the merge",
        ),
    ],
)
def test_a_warning_names_the_file_that_holds_the_key(
    tmp_path: Path, parent: str, said: str
) -> None:
    holder, child = _chain(tmp_path, parent, "[workflow]\nprofile = false\n")
    forget_old_forms_told()

    with pytest.warns(ConfigKeyRenamedWarning) as told:
        load_toml_with_base_config(child)

    messages = [str(warning.message) for warning in told]
    assert any(said in message for message in messages)
    for message in messages:
        assert message.startswith(f"{holder}: ")
        assert f"hmp doctor --fix-config {holder}" in message


def test_the_doctor_reads_what_a_parent_holds(tmp_path: Path) -> None:
    """The count of steps sits in the child, its step in the parent."""
    _, child = _chain(
        tmp_path,
        '[simulation.time]\nstep_value = 1\nstep_unit = "month"\n',
        "[calibration.outputs.net.extent]\nmaximal_flowing_steps = 2\n",
    )

    fix_config_chain(child)

    extent = tomllib.loads(child.read_text())["calibration"]["outputs"]["net"]["extent"]
    assert extent == {"maximal_flowing_duration": "2 months"}


def test_the_doctor_reads_the_method_a_parent_holds(tmp_path: Path) -> None:
    _, child = _chain(
        tmp_path,
        '[calibration]\nmethod = "cma_es"\nmax_trials = 50\n',
        "[calibration.method_options]\nmax_evaluations = 80\n",
    )

    fix_config_chain(child)

    assert tomllib.loads(child.read_text())["calibration"] == {"max_trials": 50}


@pytest.mark.parametrize(
    ("parent", "child", "said"),
    [
        pytest.param(
            "[calibration.protocol]\ntransient_method_options = { max_iter = 50 }\n",
            '[calibration.protocol]\ntransient_method = "gp_mapping"\n',
            "max_iter -> transient_max_trials = 50",
            id="the-method-of-a-search-option",
        ),
        pytest.param(
            "[calibration.uncertainty]\ntolerance = 25\n",
            '[calibration]\nobjective = "distance_gap"\n',
            "tolerance -> cost_margin = '25 m'",
            id="what-a-width-is-scored-on",
        ),
        pytest.param(
            "[calibration.outputs.net.extent]\nmaximal_flowing_steps = 2\n",
            '[simulation.time]\nstep_value = 1\nstep_unit = "month"\n',
            "maximal_flowing_steps -> maximal_flowing_duration",
            id="the-step-of-a-count",
        ),
        pytest.param(
            "[modflow6.sgrid.vertical]\nnlay = 2\n\n[modflownwt.sgrid.vertical]\nnlay = 3\n",
            '[[simulation.process]]\nid = "flow"\nkind = "flow"\nsolvers = ["modflow_nwt"]\n',
            "modflownwt.sgrid.vertical -> [domain.layers]",
            id="the-flow-solver-of-a-layering",
        ),
    ],
)
def test_the_doctor_leaves_a_parent_whose_rewrite_hangs_on_its_child(
    tmp_path: Path, parent: str, child: str, said: str
) -> None:
    """A sibling can read the same parent key otherwise, so the child's reading stays out of it."""
    holder, leaf = _chain(tmp_path, parent, child)

    changes = fix_config_chain(leaf)

    assert holder.read_text() == parent
    assert changes[leaf] == []
    assert len(changes[holder]) >= 1
    line = next(change for change in changes[holder] if said in change)
    assert CANNOT_REWRITE in line
    assert "child.toml" in line
    assert "remove the old key from parent.toml" in line


def test_a_sibling_keeps_its_reading_of_a_parent_the_doctor_left(tmp_path: Path) -> None:
    holder, child = _chain(
        tmp_path,
        "[calibration.protocol]\ntransient_method_options = { max_iter = 50 }\n",
        '[calibration.protocol]\ntransient_method = "gp_mapping"\n',
    )
    sibling = tmp_path / "sibling.toml"
    sibling.write_text(
        'base_config = "parent.toml"\n[calibration.protocol]\ntransient_method = "da_mh_gp"\n',
        encoding="utf-8",
    )

    fix_config_chain(child)

    assert "max_iter" in holder.read_text()
    with pytest.raises(ConfigValidationError, match=r"transient_method_options.max_iter -> chain"):
        load_toml_with_base_config(sibling)


def test_the_doctor_writes_nothing_when_a_rewrite_would_change_what_the_chain_reads(
    tmp_path: Path,
) -> None:
    """Toggles of one table become two lists, and the second would replace the first."""
    parent, child = _chain(
        tmp_path,
        '[export]\nnetcdf = true\nvariables = ["head"]\n',
        "[export]\nvtu = true\n",
    )
    written = parent.read_text(), child.read_text()

    with pytest.raises(ConfigError, match=r"would change what they read at export"):
        fix_config_chain(child)

    assert (parent.read_text(), child.read_text()) == written


def test_the_doctor_follows_a_directive_of_a_renamed_key_and_a_list_a_child_adds(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        "[calibration]\nmax_iter__delete = true\n\n[[calibration.phases__append]]\n"
        'name = "late"\nmax_iter = 3\n',
    )

    fix_config_file(path)

    calibration = tomllib.loads(path.read_text())["calibration"]
    assert calibration == {
        "max_trials__delete": True,
        "phases__append": [{"name": "late", "max_trials": 3}],
    }


def test_a_renamed_field_is_rewritten_where_a_table_names_it(tmp_path: Path) -> None:
    config = tmp_path / "run.toml"
    config.write_text(
        '[[export]]\nvariables = ["head", "accumulation_flux"]\nformat = "netcdf"\n\n'
        '[[export]]\nvariables = "fluxes_from_budget"\nformat = "netcdf"\n\n'
        '[display.overrides.simulated_active_network_map]\nvariable = "accumulation_flux"\n',
        encoding="utf-8",
    )

    changes = fix_config_file(config)

    text = config.read_text(encoding="utf-8")
    assert "drain_accumulation_flux" in text
    assert "budget_flux_per_area" in text
    assert '"accumulation_flux"' not in text
    assert len(changes) == 3


_ONE_DRAIN_AND_A_RATE = """
[flow]
active_bc = ["drainage"]
active_sinks_sources = ["recharge"]

[flow.bc.drainage]
value = 0.5

[flow.sinks_sources.recharge]
values = 2.0
"""


def _flow_after(body: str) -> dict:
    doc = tomllib.loads(body)
    migrate_config_doc(doc)
    return doc["flow"]


def test_a_listed_table_stays_as_it_is_and_the_lists_go() -> None:
    flow = _flow_after(_ONE_DRAIN_AND_A_RATE)
    assert flow == {
        "bc": {"drainage": {"value": 0.5}},
        "sinks_sources": {"recharge": {"values": 2.0}},
    }


@pytest.mark.parametrize(
    ("body", "path"),
    [
        ("active_bc = []\n[flow.bc.ocean]\nvalue = 0.0", ("bc", "ocean")),
        ('active_bc = ["drainage"]\n[flow.bc.west_side]\nvalue = 3.0', ("bc", "west_side")),
        (
            "active_sinks_sources = []\n[flow.sinks_sources.recharge]\nvalues = 1.0",
            ("sinks_sources", "recharge"),
        ),
        (
            'active_sinks_sources = ["recharge"]\n[flow.sinks_sources.etp]\nvalues = 1.0',
            ("sinks_sources", "etp"),
        ),
        (
            "active_bc = []\n[flow.sinks_sources.lakes.a]\nbedleak = 1e-6\nstageinit = 4.0",
            ("sinks_sources", "lakes", "a"),
        ),
        (
            "active_bc = []\n[flow.sinks_sources.sfr.net]\nmanning = 0.03",
            ("sinks_sources", "sfr", "net"),
        ),
        (
            "active_sinks_sources = []\n[flow.sinks_sources.wells.w]\nflux = -1.0",
            ("sinks_sources", "wells", "w"),
        ),
    ],
)
def test_a_table_present_and_not_listed_is_switched_off(body: str, path: tuple[str, ...]) -> None:
    node = _flow_after(f"[flow]\n{body}\n")
    for part in path:
        node = node[part]
    assert node["enabled"] is False


@pytest.mark.parametrize(
    ("body", "path"),
    [
        ('active_bc = ["drainage"]', ("bc", "drainage")),
        ('active_bc = ["ocean"]', ("bc", "ocean")),
        ('active_sinks_sources = ["recharge"]', ("sinks_sources", "recharge")),
        ('active_sinks_sources = ["etp"]', ("sinks_sources", "etp")),
        ('active_sinks_sources = ["wells"]', ("sinks_sources", "wells")),
        ('active_bc = ["lake"]', ("sinks_sources", "lakes")),
        ('active_bc = ["reservoir"]', ("sinks_sources", "lakes")),
        ('active_bc = ["sfr"]', ("sinks_sources", "sfr")),
    ],
)
def test_a_name_listed_with_no_table_gets_an_empty_one(body: str, path: tuple[str, ...]) -> None:
    node = _flow_after(f"[flow]\n{body}\n")
    for part in path:
        node = node[part]
    assert node == {}


def test_one_list_written_makes_the_other_empty() -> None:
    flow = _flow_after(
        '[flow]\nactive_bc = ["drainage"]\n[flow.sinks_sources.recharge]\nvalues = 1.0\n'
    )
    assert flow["sinks_sources"]["recharge"]["enabled"] is False


def test_a_file_with_no_list_reads_under_the_new_rule() -> None:
    body = "[flow.bc.drainage]\n[flow.sinks_sources.recharge]\nvalues = 1.0\n"
    doc = tomllib.loads(body)
    assert migrate_config_doc(doc) == []
    assert doc == tomllib.loads(body)


def test_the_doctor_keeps_comments_and_a_listed_table(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[flow]\n# what the run builds\nactive_bc = ["drainage"]\n'
        'flow_regime = "steady"\n\n# a head kept for later\n[flow.bc.ocean]\nvalue = 0.0\n',
    )
    fix_config_file(path)
    text = path.read_text()
    flow = tomllib.loads(text)["flow"]
    assert "active_bc" not in flow
    assert flow["bc"]["drainage"] == {}
    assert flow["bc"]["ocean"] == {"value": 0.0, "enabled": False}
    assert "# a head kept for later" in text
    assert fix_config_file(path) == []


def test_a_list_in_a_child_folds_there_and_leaves_the_parent(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text(
        "[flow.bc.drainage]\n[flow.bc.ocean]\nvalue = 0.0\n", encoding="utf-8"
    )
    child = tmp_path / "child.toml"
    child.write_text('base_config = "base.toml"\n[flow]\nactive_bc = ["ocean"]\n', encoding="utf-8")
    chain = fix_config_chain(child)
    assert chain[(tmp_path / "base.toml").resolve()] == []
    flow = tomllib.loads(child.read_text())["flow"]
    assert flow == {"bc": {"drainage": {"enabled": False}}}


def test_a_list_in_a_parent_lets_a_child_switch_off_what_it_adds(tmp_path: Path) -> None:
    base = tmp_path / "base.toml"
    base.write_text('[flow]\nactive_bc = ["drainage"]\n', encoding="utf-8")
    child = tmp_path / "child.toml"
    child.write_text(
        'base_config = "base.toml"\n[flow.bc.west_side]\nvalue = 3.0\n', encoding="utf-8"
    )
    fix_config_chain(child)
    assert tomllib.loads(base.read_text())["flow"] == {"bc": {"drainage": {}}}
    assert tomllib.loads(child.read_text())["flow"]["bc"]["west_side"]["enabled"] is False


def test_a_child_that_appends_to_a_list_reads_as_the_merge() -> None:
    layers = [
        (
            "base.toml",
            tomllib.loads('[flow]\nactive_bc = ["drainage"]\n[flow.bc.ocean]\nvalue = 0.0\n'),
        ),
        ("child.toml", tomllib.loads('[flow]\nactive_bc__append = ["ocean"]\n')),
    ]
    from hydromodpy.core.toml_io.merge import merge_toml_payloads

    merged = merge_toml_payloads(layers[0][1], layers[1][1])
    migrate_config_doc(merged)
    assert merged["flow"]["bc"]["ocean"] == {"value": 0.0}
    assert merged["flow"]["bc"]["drainage"] == {}


def test_a_phase_that_overrides_a_list_says_it_table_by_table() -> None:
    doc = tomllib.loads(
        "[flow]\n"
        'active_bc = ["drainage", "sfr"]\n'
        "[flow.sinks_sources.sfr.net]\nmanning = 0.03\n"
        "[[calibration.phases]]\n"
        'name = "drains"\n'
        '[calibration.phases.overrides]\n"flow.active_bc" = ["drainage"]\n'
        "[[calibration.phases]]\n"
        'name = "streams"\n'
        '[calibration.phases.overrides]\n"flow.active_bc" = ["drainage", "sfr"]\n'
    )
    migrate_config_doc(doc)
    first, second = (phase["overrides"] for phase in doc["calibration"]["phases"])
    assert first == {
        "flow.bc.drainage.enabled": True,
        "flow.sinks_sources.sfr.net.enabled": False,
    }
    assert second == {
        "flow.bc.drainage.enabled": True,
        "flow.sinks_sources.sfr.net.enabled": True,
    }


@pytest.mark.parametrize(
    ("old", "new", "section", "key"),
    [
        ("flow.runtime_backend", "flow.runtime.backend", "flow", "runtime_backend"),
        (
            "flow.surface_interaction_model",
            "flow.runtime.surface_interaction_model",
            "flow",
            "surface_interaction_model",
        ),
        (
            "flow.runtime_max_iterations",
            "flow.runtime.max_iterations",
            "flow",
            "runtime_max_iterations",
        ),
        ("flow.ic.type", "flow.ic.kind", "flow.ic", "type"),
        (
            "geographic.catchment.catch_def",
            "geographic.catchment.kind",
            "geographic.catchment",
            "catch_def",
        ),
        ("solver.backend.backend", "solver.backend.kind", "solver.backend", "backend"),
        ("flow.param.K33.field.value", "flow.param.Kv.field.value", "", ""),
        (
            "transport.modflow6prt.parameters.stop_time_days",
            "transport.modflow6prt.parameters.stop_time",
            "transport.modflow6prt.parameters",
            "stop_time_days",
        ),
    ],
)
def test_a_renamed_key_is_rewritten_as_a_key_and_as_a_path(
    old: str, new: str, section: str, key: str
) -> None:
    assert rewrite_dotted_path(old) == new
    if not section:
        return
    doc: dict = {}
    node = doc
    for part in section.split("."):
        node = node.setdefault(part, {})
    node[key] = "x"
    migrate_config_doc(doc)
    node = doc
    for part in new.split("."):
        node = node[part]
    assert node == "x"


@pytest.mark.parametrize("kind", ["cauchy", "robin"])
def test_both_old_drain_kinds_are_one_drain(kind: str) -> None:
    flow = _flow_after(f'[flow.bc.drainage]\nkind = "{kind}"\n')
    assert flow["bc"]["drainage"]["kind"] == "drain"


def test_an_old_property_id_is_rewritten_everywhere_it_stands() -> None:
    flow = _flow_after(
        '[flow]\nparam_list = ["K", "K33"]\n[flow.param.K33.field]\nid = "K33"\nkind = "homogeneous"\n'
        "value = 1e-6\n"
    )
    assert flow["param_list"] == ["K", "Kv"]
    assert "K33" not in flow["param"]
    assert flow["param"]["Kv"]["field"]["id"] == "Kv"


@pytest.mark.parametrize("name", ["Kz", "Kx", "Ky"])
def test_an_id_no_solver_read_is_refused_and_not_rewritten(name: str) -> None:
    from hydromodpy.physics.flow.flow_config import FlowConfig

    payload = {name: {"field": {"kind": "homogeneous", "value": 1e-6, "unit": "m/s"}}}
    with pytest.raises(ValueError, match="never been read"):
        FlowConfig(param=payload, param_list=[name])


def test_the_keys_transport_never_read_are_dropped() -> None:
    doc = tomllib.loads(
        "[transport]\nactive_bc = []\nactive_sinks_sources = []\nparam_list = []\n"
        "[transport.modflow6prt.parameters]\nporosity = 0.2\n"
    )
    migrate_config_doc(doc)
    assert set(doc["transport"]) == {"modflow6prt"}


def test_a_bare_buffer_is_written_out_with_the_same_rule() -> None:
    doc = tomllib.loads("[geographic.catchment]\nbuff_area = 10\n")
    migrate_config_doc(doc)
    assert doc["geographic"]["catchment"]["buff_area"] == "10% of sqrt(area)"
    again = tomllib.loads('[geographic.catchment]\nbuff_area = "10%"\n')
    assert migrate_config_doc(again) == []


_FREE_TABLES = ("flow.param", "display.overrides")
"""Tables that hold free names, which the grammar lists without them."""


def _keys_of_the_grammar() -> set[str]:
    return {row.split("\t", 1)[0] for row in toml_fields()}


def _a_key_the_models_hold(path: str, keys: set[str]) -> bool:
    if path.startswith("flow.ic.") and not path.startswith("flow.ic.h."):
        path = path.replace("flow.ic.", "flow.ic.h.", 1)
    if any(path.startswith(f"{table}.") for table in _FREE_TABLES):
        return True
    return path in keys or any(key.startswith(f"{path}.") for key in keys)


@pytest.mark.parametrize("form", old_forms(), ids=lambda form: form.old)
def test_every_listed_key_is_held_against_the_models(form: OldForm) -> None:
    """A new name leads to a key the models have, and an old one left them."""
    keys = _keys_of_the_grammar()
    old = document_path(form.old)
    if form.new is not None:
        assert _a_key_the_models_hold(document_path(form.new), keys), (
            f"{form.old} leads to {form.new}, which no model holds"
        )
    # A table that changed shape and kept its name: the toggles of [export.variables].
    assert old not in keys or "{*}" in form.old, f"{form.old} is still a key"


@pytest.mark.parametrize(("key", "old", "new"), OLD_VALUES)
def test_every_rewritten_value_is_held_against_its_key(key: str, old: str, new: str) -> None:
    assert key in _keys_of_the_grammar()
    assert old != new


def _steps(path: str) -> list[str]:
    """Split a form path into keys: ``{*}`` is the free name ``x``, ``[*]`` a list index."""
    steps: list[str] = []
    for part in path.split("."):
        if part == "{*}":
            steps.append("x")
            continue
        steps.append(part.removesuffix("[*]"))
        if part.endswith("[*]"):
            steps.append("[0]")
    return steps


def _document_with(path: str, value: object) -> dict:
    """Return a document that holds *value* at *path*, a table of a list or a free name included."""
    steps = _steps(path)
    root: dict = {}
    node: object = root
    for index, step in enumerate(steps):
        last = index == len(steps) - 1
        following = steps[index + 1] if not last else ""
        if step == "[0]":
            continue
        child: object = value if last else ([{}] if following == "[0]" else {})
        node[step] = child  # type: ignore[index]
        node = child[0] if isinstance(child, list) else child
    return root


def _dig(doc: object, path: str) -> object:
    for step in _steps(path):
        doc = doc[0] if step == "[0]" else doc[step]  # type: ignore[index]
    return doc


_PLAIN_RENAMES = [rule for rule in RENAMED_KEYS if rule.convert is None and not rule.sealed_only]
_FLOW_RENAMES = [rule for rule in _PLAIN_RENAMES if rule.scope.split(".")[0] in {"flow", "solver"}]


@pytest.mark.parametrize(
    "rule", _FLOW_RENAMES, ids=lambda rule: f"{rule.scope}.{rule.old}->{rule.new}"
)
def test_a_renamed_key_is_rewritten_by_the_doctor_with_its_version(rule, tmp_path: Path) -> None:
    """Each plain rename of a table moves its key through ``hmp doctor --fix-config``."""
    import tomlkit

    assert Version(rule.since) >= Version(ALPHA_FORM)
    doc = _document_with(f"{rule.scope}.{rule.old}", "probe-value")
    path = _write(tmp_path, tomlkit.dumps(doc))
    fix_config_file(path)
    after = tomllib.loads(path.read_text(encoding="utf-8"))
    assert _dig(after, f"{rule.scope}.{rule.new}") == "probe-value"
    assert rule.old not in _dig(after, rule.scope)
    assert fix_config_file(path) == []


@pytest.mark.parametrize("move", MOVED_TABLES, ids=lambda move: f"{move.old}->{move.new}")
def test_a_moved_table_is_rewritten_by_the_doctor_with_its_version(move, tmp_path: Path) -> None:
    import tomlkit

    assert Version(move.since) >= Version(ALPHA_FORM)
    if "sgrid" in move.old:
        pytest.skip("the layering needs a solver to choose its table, tested above")
    doc = _document_with(move.old, "probe-value")
    path = _write(tmp_path, tomlkit.dumps(doc))
    fix_config_file(path)
    after = tomllib.loads(path.read_text(encoding="utf-8"))
    assert _dig(after, move.new) == "probe-value"
    assert fix_config_file(path) == []


def test_every_key_the_tables_write_is_held_by_the_models() -> None:
    """The new name of every row, a moved table and a hand-written form included, is a key."""
    keys = _keys_of_the_grammar()
    lost = [
        f"{form.old} -> {form.new}"
        for form in old_forms()
        if form.new is not None
        and form.rewritten
        and not _a_key_the_models_hold(document_path(form.new), keys)
    ]
    assert lost == []


# The calibration forms a count, a station or a default stood for.

_MONTHLY = '[simulation.time]\nstart_datetime = "2000-01-01"\nstep_value = 1\nstep_unit = "month"\n'
_DAILY = '[simulation.time]\nstart_datetime = "2015-01-01"\nstep_value = "1 day"\n'
_BLOCK = '[[calibration.objective_blocks]]\nname = "b"\nuses_outputs = ["q"]\n'
_GAUGE = '[site]\ngauge = "G"\n'


@pytest.mark.parametrize(
    ("text", "kept", "gone", "told"),
    [
        (
            _MONTHLY + "[calibration]\nwarmup_periods = 12\n",
            "window",
            "warmup_periods",
            "2001-01-01",
        ),
        (
            _DAILY + "[calibration]\nwarmup_periods = 30\n",
            "window",
            "warmup_periods",
            "2015-01-31",
        ),
        (_DAILY + "[calibration]\nwarmup_periods = 0\n", None, "warmup_periods", "skipped nothing"),
        ("[calibration]\nwarmup_periods = 12\n", "warmup_periods", None, "[simulation.time]"),
        (
            '[simulation.time]\nstep_value = "1 day"\n[calibration]\nwarmup_periods = 3\n',
            "warmup_periods",
            None,
            "start_datetime is not in this file",
        ),
        (
            _DAILY + "[calibration]\nwarmup_periods = 3\nwindow = {start = '2016-01-01'}\n",
            "warmup_periods",
            None,
            "keep one",
        ),
        (
            _DAILY + "[calibration]\n" + _BLOCK + "warmup = 3\n",
            "warmup",
            None,
            "once for all blocks",
        ),
        (_DAILY + "[calibration]\n" + _BLOCK + "warmup = 0\n", None, "warmup", "skipped nothing"),
        (
            _GAUGE + '[calibration]\nobserved_station_id = "G"\n',
            None,
            "observed_station_id",
            "now [site] gauge",
        ),
        (
            '[calibration]\nobserved_station_id = "G"\n',
            None,
            "observed_station_id",
            "now [site] gauge",
        ),
        (
            _GAUGE + '[calibration]\nobserved_station_id = "H"\n',
            "observed_station_id",
            None,
            "keep one",
        ),
        (
            _GAUGE + '[calibration.protocol]\nname = "p"\nobserved_station_id = "G"\n',
            None,
            "observed_station_id",
            "now [site] gauge",
        ),
        (
            _GAUGE + '[[calibration.phases]]\nname = "k"\nobserved_station_id = "G"\n',
            None,
            "observed_station_id",
            "now [site] gauge",
        ),
        ("[calibration]\n" + _BLOCK, "metric", None, "now required"),
        (
            "[calibration]\nobjective = 'kge'\n" + _BLOCK + "metric = 'nse'\n",
            None,
            "objective",
            "own metric",
        ),
        (
            "[calibration]\nobjective = 'kge'\n"
            + _BLOCK
            + "metric = 'nse'\n[[calibration.phases]]\nname = 'p'\nvariable = 'head'\n",
            "objective",
            None,
            "a phase scores a variable",
        ),
        (
            "[calibration]\npersistence = {save_lock = true}\nlightweight_extraction = true\npersist_model_distribution = false\n",
            None,
            "persistence",
            "no step ever read it",
        ),
        (
            "[calibration.aggregate]\nweighting = 'error'\nnested_gauges = 'x'\non_member_failure = 'drop'\nmin_samples = 2\n",
            "min_samples",
            "weighting",
            "no step ever read it",
        ),
    ],
    ids=[
        "a count of monthly steps is a date",
        "a count of daily steps is a date",
        "zero skipped nothing",
        "no time grid leaves the count",
        "no start date leaves the count",
        "a window beside the count leaves it",
        "a block burn-in has no date",
        "a block burn-in of zero goes",
        "a station equal to the gauge goes",
        "a station without a gauge becomes the gauge",
        "a station other than the gauge stays",
        "a protocol station goes",
        "a phase station goes",
        "a block gets the old default metric",
        "an objective beside blocks goes",
        "an objective a phase reads stays",
        "the dead calibration keys go",
        "the dead aggregate keys go",
    ],
)
def test_the_doctor_rewrites_the_calibration_forms(tmp_path: Path, text, kept, gone, told) -> None:
    path = _write(tmp_path, text)

    changes = fix_config_file(path)

    flat = path.read_text(encoding="utf-8")
    assert told in " ".join(changes)
    assert kept is None or kept in flat
    assert gone is None or f"{gone} =" not in flat
    assert fix_config_file(path) == [c for c in changes if CANNOT_REWRITE in c]


_WARMUP_MOVED = (
    "calibration.warmup_periods -> window (start {}, counted from start_datetime; the old count "
    "ran from the first aligned sample, so the date equals it only when the record starts at "
    "start_datetime)"
)
_J1 = '[site]\ngauge = "J1"\n'


@pytest.mark.parametrize(
    ("parent", "child", "parent_after", "child_after", "parent_told", "child_told"),
    [
        (
            _MONTHLY + _J1,
            "[calibration]\nwarmup_periods = 2\n",
            None,
            {"calibration": {"window": {"start": "2000-03-01"}}},
            [],
            [_WARMUP_MOVED.format("2000-03-01")],
        ),
        (
            _J1,
            '[calibration]\nobserved_station_id = "J1"\n',
            None,
            {"calibration": {}},
            [],
            ["calibration.observed_station_id dropped (now [site] gauge)"],
        ),
        (
            _J1,
            '[calibration]\nobserved_station_id = "J9"\n',
            None,
            {"calibration": {"observed_station_id": "J9"}},
            [],
            [f"calibration.observed_station_id{CANNOT_REWRITE}[site] gauge is 'J1', keep one"],
        ),
        (
            "[simulation]\nname = 'n'\n",
            '[calibration]\nobserved_station_id = "J9"\n',
            None,
            {"calibration": {}, "site": {"gauge": "J9"}},
            [],
            ["calibration.observed_station_id dropped (now [site] gauge)"],
        ),
    ],
    ids=[
        "the step sits in the parent",
        "the gauge of the parent says the same",
        "the gauge of the parent says another station",
        "no file names a gauge",
    ],
)
def test_the_doctor_reads_the_files_above_for_a_step_or_a_gauge(
    tmp_path: Path, parent, child, parent_after, child_after, parent_told, child_told
) -> None:
    base = tmp_path / "base.toml"
    base.write_text(parent, encoding="utf-8")
    leaf = tmp_path / "leaf.toml"
    leaf.write_text(f'base_config = "base.toml"\n{child}', encoding="utf-8")
    parent_before = tomllib.loads(parent)

    told = fix_config_chain(leaf)

    assert told == {base: parent_told, leaf: child_told}
    assert tomllib.loads(base.read_text(encoding="utf-8")) == (parent_after or parent_before)
    assert tomllib.loads(leaf.read_text(encoding="utf-8")) == {
        "base_config": "base.toml",
        **child_after,
    }


def test_a_count_in_a_parent_whose_step_a_child_writes_is_left_in_the_parent(
    tmp_path: Path,
) -> None:
    base = tmp_path / "base.toml"
    base.write_text("[calibration]\nwarmup_periods = 2\n", encoding="utf-8")
    leaf = tmp_path / "leaf.toml"
    leaf.write_text(f'base_config = "base.toml"\n{_MONTHLY}', encoding="utf-8")

    told = fix_config_chain(leaf)

    assert told[leaf] == []
    assert len(told[base]) == 1
    assert told[base][0].startswith("calibration.warmup_periods -> window (start 2000-03-01")
    assert CANNOT_REWRITE in told[base][0]
    assert "warmup_periods = 2" in base.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("start", "written"),
    [("2015-01-01T12:00:00", "2015-01-04"), ("2015-01-01", "2015-01-04")],
    ids=["a time of day is cut to the day", "a plain date"],
)
def test_the_date_a_count_stood_for_is_a_day_and_the_change_says_what_it_counts_from(
    tmp_path: Path, start: str, written: str
) -> None:
    path = _write(
        tmp_path,
        f'[simulation.time]\nstart_datetime = "{start}"\nstep_value = "1 day"\n'
        "[calibration]\nwarmup_periods = 3\n",
    )

    assert fix_config_file(path) == [_WARMUP_MOVED.format(written)]
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["calibration"] == {"window": {"start": written}}


def test_the_doctor_writes_the_gauge_a_station_stood_for(tmp_path: Path) -> None:
    path = _write(tmp_path, '[calibration]\nobserved_station_id = "G"\n')

    fix_config_file(path)

    assert tomllib.loads(path.read_text(encoding="utf-8"))["site"] == {"gauge": "G"}


def test_the_doctor_writes_the_date_a_count_stood_for(tmp_path: Path) -> None:
    path = _write(tmp_path, _MONTHLY + "[calibration]\nwarmup_periods = 12\n")

    fix_config_file(path)

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["calibration"] == {"window": {"start": "2001-01-01"}}


_OLD_WINDOW = "{start = '2001-01-01'}"


@pytest.mark.parametrize(
    ("body", "where", "value"),
    [
        (f"[calibration]\nscoring_window = {_OLD_WINDOW}\n", ("window",), {"start": "2001-01-01"}),
        (
            f'[[calibration.phases]]\nname = "p"\nscoring_window = {_OLD_WINDOW}\n',
            ("phases", 0, "window"),
            {"start": "2001-01-01"},
        ),
        (
            f'[calibration.protocol]\nname = "m"\nscoring_window = {_OLD_WINDOW}\n',
            ("protocol", "window"),
            {"start": "2001-01-01"},
        ),
        (
            '[[calibration.phases]]\nname = "p"\n[calibration.phases.overrides]\n'
            '"calibration.scoring_window.start" = "2002-01-01"\n',
            ("phases", 0, "overrides", "calibration.window.start"),
            "2002-01-01",
        ),
        (
            '[calibration.parameters.k]\npath = "calibration.scoring_window.start"\n',
            ("parameters", "k", "path"),
            "calibration.window.start",
        ),
    ],
    ids=["section", "phase", "protocol", "override-key", "parameter-path"],
)
def test_scoring_window_is_renamed_window_in_every_form(tmp_path: Path, body, where, value) -> None:
    path = _write(tmp_path, body)

    assert fix_config_file(path)

    found = tomllib.loads(path.read_text())["calibration"]
    for step in where:
        found = found[step]
    assert found == value


def test_a_sealed_scoring_window_reads_as_window() -> None:
    from hydromodpy.config.config_migration import migrate_sealed_config_doc

    window = {"start": "2001-01-01"}
    doc = {
        "calibration": {
            "scoring_window": window,
            "phases": [{"name": "p", "scoring_window": window}],
            "protocol": {"name": "m", "scoring_window": window},
        }
    }

    migrate_sealed_config_doc(doc)

    assert doc == {
        "calibration": {
            "window": window,
            "phases": [{"name": "p", "window": window}],
            "protocol": {"name": "m", "window": window},
        }
    }


def test_a_sealed_config_drops_what_a_replay_never_reads() -> None:
    from hydromodpy.config.config_migration import migrate_sealed_config_doc

    doc = {
        "site": {"gauge": "G"},
        "calibration": {
            "warmup_periods": 12,
            "observed_station_id": "H",
            "objective": "nse",
            "persistence": {"save_lock": True},
            "lightweight_extraction": True,
            "aggregate": {"weighting": "area", "min_samples": 2},
            "protocol": {"name": "p", "observed_station_id": "H"},
            "objective_blocks": [{"name": "b", "uses_outputs": ["q"], "warmup": 3}],
            "phases": [{"name": "k", "observed_station_id": "H"}],
        },
    }

    changes = migrate_sealed_config_doc(doc)

    assert doc == {
        "site": {"gauge": "G"},
        "calibration": {
            "aggregate": {"min_samples": 2},
            "protocol": {"name": "p"},
            "objective_blocks": [{"name": "b", "uses_outputs": ["q"], "metric": "rmse"}],
            "phases": [{"name": "k"}],
        },
    }
    assert len(changes) == 10


# The flat keys of a network output move to the tables map, model and verdict.

_FLAT = '[calibration.outputs.net]\nsupport = "network"\n'
_ONE_MAP = {"complete": "s.gpkg"}
_TWO_MAPS = {"complete": "data.hydrography", "permanent": "p.gpkg"}

_OLD_EXTENT = {"maximal_flowing_duration": "1 month", "weights": {"minimal": 0.25, "maximal": 0.75}}
_NEW_EXTENT = {
    "flowing_at_least": "1 month",
    "dry_at_most": None,
    "year_quorum": 0.5,
    "visible_flow": "1 L/s",
}
_EVERY_MOVE = [
    ("observed_network", "data.hydrography", "map.complete", "data.hydrography"),
    ("minimal_stream_geometry_path", "p.gpkg", "map.permanent", "p.gpkg"),
    ("observed_rasterization", "heads", "map.drawn_by", "heads"),
    ("clip_map_to_catchment", False, "map.clip_to_catchment", False),
    ("heads_snap_radius", 80.0, "map.heads.radius", 80.0),
    ("heads_min_drained_area_km2", 0.1, "map.heads.min_drained_area", 0.1),
    ("observed_position_accuracy", 50.0, "map.position_accuracy", 50.0),
    ("tau_specific_ratio", 0.002, "model.seepage_threshold", 0.002),
    ("diagonal_neighbors", True, "model.neighbours", "D8"),
    ("weighting", "area", "model.weighting", "area"),
    ("validity_length", "auto", "verdict.validity_length", "auto"),
    ("on_roptim_violation", "error", "verdict.on_invalid", "error"),
    ("alpha_warning_threshold", 0.8, "verdict.alpha_warning_threshold", 0.8),
    ("clipping_warning_share", 0.2, "verdict.clipping_warning_share", 0.2),
    ("clipping_warning_gap", 0.1, "verdict.clipping_warning_gap", 0.1),
    ("extent", _OLD_EXTENT, "model.extent", _NEW_EXTENT),
]


@pytest.mark.parametrize("reading", ["the doctor", "a snapshot", "a sealed file"])
def test_a_network_output_written_flat_reads_back_with_the_same_values(
    tmp_path: Path, reading: str
) -> None:
    flat = {"support": "network", **{row[0]: row[1] for row in _EVERY_MOVE}}
    doc = {"calibration": {"outputs": {"net": copy.deepcopy(flat)}}}
    if reading == "the doctor":
        path = _write(tmp_path, tomlkit.dumps(doc))
        fix_config_file(path)
        doc = tomllib.loads(path.read_text())
    elif reading == "a snapshot":
        migrate_sealed_config_doc(doc)
    else:
        migrate_config_doc_on_load(doc, source=tmp_path / "runs" / "n" / "config.toml")

    read = validate_calib_output(doc["calibration"]["outputs"]["net"]).model_dump(mode="json")
    moved = {new: _value_at(read, new) for _old, _value, new, _today in _EVERY_MOVE}
    assert moved == {new: today for _old, _value, new, today in _EVERY_MOVE}
    assert read["map"]["calibrate_on"] == {"permanent": 0.25, "complete": 0.75}


_NETWORK_REWRITES = {
    "two maps in one state, the four neighbours": (
        'observed_network = "data.hydrography"\nminimal_stream_geometry_path = "p.gpkg"\n'
        "diagonal_neighbors = false\n",
        {"map": {**_TWO_MAPS, "calibrate_on": "permanent"}, "model": {"neighbours": "D4"}},
    ),
    "two maps whose role is already written": (
        'observed_network = "data.hydrography"\nminimal_stream_geometry_path = "p.gpkg"\n'
        '[calibration.outputs.net.map]\ncalibrate_on = "complete"\n',
        {"map": {**_TWO_MAPS, "calibrate_on": "complete"}},
    ),
    "two maps and an extent": (
        'observed_network = "data.hydrography"\nminimal_stream_geometry_path = "p.gpkg"\n'
        "[calibration.outputs.net.extent]\nyear_quorum = 1.0\n",
        {
            "map": {**_TWO_MAPS, "calibrate_on": {"permanent": 0.5, "complete": 0.5}},
            "model": {"extent": {"year_quorum": 1.0}},
        },
    ),
    "two maps whose role says what the old weights say": (
        'observed_network = "data.hydrography"\nminimal_stream_geometry_path = "p.gpkg"\n'
        "[calibration.outputs.net.map]\ncalibrate_on = { permanent = 0.25, complete = 0.75 }\n"
        "[calibration.outputs.net.extent]\nyear_quorum = 1.0\n"
        "[calibration.outputs.net.extent.weights]\nminimal = 0.25\nmaximal = 0.75\n",
        {
            "map": {**_TWO_MAPS, "calibrate_on": {"permanent": 0.25, "complete": 0.75}},
            "model": {"extent": {"year_quorum": 1.0}},
        },
    ),
    "one map, its weights go, the steps rule runs first": (
        'stream_geometry_path = "s.gpkg"\n[calibration.outputs.net.extent]\n'
        "maximal_flowing_steps = 2\n[calibration.outputs.net.extent.weights]\nminimal = 0.5\n"
        "maximal = 0.5\n" + _MONTHLY,
        {"map": _ONE_MAP, "model": {"extent": {"flowing_at_least": "2 months"}}},
    ),
    "settings no rule reads, a verdict already written": (
        'stream_geometry_path = "s.gpkg"\nobserved_rasterization = "crossing"\n'
        'heads_snap_radius = "80 m"\nobserved_position_accuracy = "50 m"\n'
        'validity_length = "150 m"\n'
        "[calibration.outputs.net.verdict]\nmax_catchment_mismatch = false\n",
        {
            "map": {**_ONE_MAP, "drawn_by": "crossing"},
            "verdict": {"validity_length": "150 m", "max_catchment_mismatch": False},
        },
    ),
}


@pytest.mark.parametrize(
    ("flat", "tables"), _NETWORK_REWRITES.values(), ids=_NETWORK_REWRITES.keys()
)
def test_the_doctor_writes_a_network_output_in_its_tables(
    tmp_path: Path, flat: str, tables: dict
) -> None:
    path = _write(tmp_path, _FLAT + flat)

    assert fix_config_file(path)
    output = tomllib.loads(path.read_text())["calibration"]["outputs"]["net"]
    assert output == {"support": "network", **tables}
    assert validate_calib_output(output).support == "network"
    assert fix_config_file(path) == []


@pytest.mark.parametrize(
    ("flat", "old", "left"),
    [
        (
            'observed_network = "geographic.river_network"\n',
            "observed_network",
            "a network the DEM derives is no observation",
        ),
        ('diagonal_neighbors = "yes"\n', "diagonal_neighbors", "'yes' is neither true nor false"),
        (
            'stream_geometry_path = "s.gpkg"\n[calibration.outputs.net.map]\ncomplete = "t"\n',
            "stream_geometry_path",
            "'map.complete' is given too, keep one",
        ),
        (
            '[calibration.outputs.net.map]\ncomplete = "s.gpkg"\npermanent = "p.gpkg"\n'
            'calibrate_on = "permanent"\n'
            "[calibration.outputs.net.extent.weights]\nminimal = 0.25\nmaximal = 0.75\n",
            "extent",
            "its weights say {'permanent': 0.25, 'complete': 0.75} and map.calibrate_on says "
            "'permanent', keep one",
        ),
    ],
    ids=["a_network_from_the_dem", "no_boolean", "given_twice", "a_role_against_old_weights"],
)
def test_what_the_doctor_cannot_write_stays_with_its_reason(
    tmp_path: Path, flat: str, old: str, left: str
) -> None:
    path = _write(tmp_path, _FLAT + flat)

    changes = fix_config_file(path)

    assert changes[0].startswith(f"calibration.outputs.net.{old}{CANNOT_REWRITE}{left}")
    assert old in tomllib.loads(path.read_text())["calibration"]["outputs"]["net"]


def test_the_doctor_writes_an_inline_output_inline_and_keeps_a_comment(tmp_path: Path) -> None:
    inline = _write(
        tmp_path,
        '[calibration.outputs]\nnet = {support = "network", stream_geometry_path = "s.gpkg"}\n',
    )
    fix_config_file(inline)
    written = tomllib.loads(inline.read_text())["calibration"]["outputs"]["net"]
    assert written == {"support": "network", "map": _ONE_MAP}

    commented = _write(tmp_path, _FLAT + 'stream_geometry_path = "s.gpkg" # the file\n')
    fix_config_file(commented)
    assert 'complete = "s.gpkg" # the file' in commented.read_text()


def test_a_child_that_adds_the_permanent_map_writes_the_role(tmp_path: Path) -> None:
    base = tmp_path / "base.toml"
    base.write_text(_FLAT + 'stream_geometry_path = "s.gpkg"\n', encoding="utf-8")
    leaf = tmp_path / "leaf.toml"
    leaf.write_text(
        'base_config = "base.toml"\n[calibration.outputs.net]\n'
        'minimal_stream_geometry_path = "p.gpkg"\n',
        encoding="utf-8",
    )

    fix_config_chain(leaf)

    assert tomllib.loads(leaf.read_text())["calibration"]["outputs"]["net"] == {
        "map": {"permanent": "p.gpkg", "calibrate_on": "permanent"}
    }
    assert tomllib.loads(base.read_text())["calibration"]["outputs"]["net"] == {
        "support": "network",
        "map": _ONE_MAP,
    }


_REWRITTEN_MAPS = (
    _FLAT + '[calibration.outputs.net.map]\ncomplete = "s.gpkg"\npermanent = "p.gpkg"\n'
)
_OLD_MAPS = (
    _FLAT + 'observed_network = "data.hydrography"\nminimal_stream_geometry_path = "p.gpkg"\n'
)
_ADDS_AN_EXTENT = "[calibration.outputs.net.extent]\nyear_quorum = 1.0\n"
_ADDS_WEIGHTS = "[calibration.outputs.net.extent.weights]\nminimal = 0.25\nmaximal = 0.75\n"
_ADDS_THE_PERMANENT_MAP = '[calibration.outputs.net]\nminimal_stream_geometry_path = "q.gpkg"\n'
_ONE_STATE = 'calibrate_on = "permanent"\n'
_SHARED = "calibrate_on = { permanent = 0.25, complete = 0.75 }\n[calibration.outputs.net.model.extent]\nyear_quorum = 1.0\n"
_CHAINS = {
    "a sibling with weights keeps them": (
        _REWRITTEN_MAPS + _ONE_STATE,
        _ADDS_WEIGHTS,
        (0.25, 0.75),
    ),
    "a sibling with an extent and no weights keeps half and half": (
        _REWRITTEN_MAPS + _ONE_STATE,
        _ADDS_AN_EXTENT,
        (0.5, 0.5),
    ),
    "a parent unwritten with both maps and a child with an extent": (
        _OLD_MAPS,
        _ADDS_AN_EXTENT,
        (0.5, 0.5),
    ),
    "a rewritten parent that shares the value keeps its share": (
        _REWRITTEN_MAPS + _SHARED,
        _ADDS_AN_EXTENT,
        (0.25, 0.75),
    ),
    "a rewritten parent with one map and an extent, a child adds the other map": (
        _FLAT
        + '[calibration.outputs.net.map]\ncomplete = "s.gpkg"\n'
        + _ADDS_AN_EXTENT.replace("net.extent", "net.model.extent"),
        _ADDS_THE_PERMANENT_MAP,
        (0.5, 0.5),
    ),
    "a rewritten role of one state stands under a new permanent map": (
        _REWRITTEN_MAPS + 'calibrate_on = "complete"\n',
        _ADDS_THE_PERMANENT_MAP,
        (0.0, 1.0),
    ),
    "a rewritten role of one state stands beside an inherited extent": (
        _REWRITTEN_MAPS + _ONE_STATE + _ADDS_AN_EXTENT.replace("net.extent", "net.model.extent"),
        _ADDS_THE_PERMANENT_MAP,
        (1.0, 0.0),
    ),
}


@pytest.mark.parametrize(("parent", "child", "shares"), _CHAINS.values(), ids=_CHAINS.keys())
def test_a_child_reads_the_share_its_old_form_scored(
    tmp_path: Path, parent: str, child: str, shares: tuple[float, float]
) -> None:
    """Two passes: a parent left for its child is rewritten once the child says its role."""
    _, leaf = _chain(tmp_path, parent, child)

    fix_config_chain(leaf)
    fix_config_chain(leaf)

    read = load_toml_with_base_config(leaf)["calibration"]["outputs"]["net"]
    weights = validate_calib_output(read).map.bound_weights
    assert (weights.permanent, weights.complete) == shares
    assert fix_config_chain(leaf) == {tmp_path / "parent.toml": [], leaf: []}


@pytest.mark.parametrize(
    "dotted",
    [
        'outputs.net.stream_geometry_path = "s.gpkg"\n',
        'outputs.net.observed_rasterization = "crossing"\noutputs.net.heads_snap_radius = 80.0\n',
        "outputs.net.extent.weights.minimal = 0.5\n",
    ],
    ids=["a_table_would_land_at_the_root", "a_key_it_cannot_remove", "an_old_extent"],
)
def test_the_doctor_refuses_an_output_held_by_dotted_keys(tmp_path: Path, dotted: str) -> None:
    text = f'[calibration]\noutputs.net.support = "network"\n{dotted}'
    path = _write(tmp_path, text)

    assert fix_config_file(path) == [
        "calibration.outputs.net"
        f"{CANNOT_REWRITE}write the output as a table [calibration.outputs.net]"
    ]
    assert path.read_text() == text
