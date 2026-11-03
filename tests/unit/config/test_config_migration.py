"""Tests for the one-shot ``hmp doctor --fix-config`` TOML rewriter."""

from __future__ import annotations

import importlib
import tomllib
import warnings
from pathlib import Path

import pytest
from packaging.version import Version

from hydromodpy.config.config_migration import (
    ALPHA_FORM,
    DEPRECATION_DELAY_MINORS,
    OldForm,
    document_path,
    fix_config_chain,
    fix_config_file,
    migrate_config_doc,
    migrate_config_doc_on_load,
    old_forms,
    outlived_forms,
)
from hydromodpy.core.config_kit.base import (
    CANNOT_REWRITE,
    ConfigKeyRenamedWarning,
    HydroModelBase,
    forget_old_forms_told,
    warn_old_form,
)
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.core.version import __version__
from tools.surface_snapshot import outlived_interface_forms


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
        "[persistence]\nsave_lock = false\n\n"
        "[calibration.persistence]\nsave_lock = true\n",
    )
    changes = fix_config_file(path)
    assert any("solver_scratch dropped" in c for c in changes)
    assert sum("save_lock dropped" in c for c in changes) == 3

    parsed = tomllib.loads(path.read_text())
    results = parsed["simulation"]["results"]
    assert "solver_scratch" not in results
    assert results["keep_solver_files"] is True
    assert "save_lock" not in results["persistence"]
    assert results["persistence"]["save_zarr"] is True
    assert "save_lock" not in parsed["persistence"]
    assert "save_lock" not in parsed["calibration"]["persistence"]
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
    assert bc["drainage"] == {"value": "1e-6 m2/s", "kind": "cauchy"}
    assert len(changes) == 2
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
    assert "hmp publish --format tar" in changes[0]
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
    assert len(changes) == 2 and "hmp publish --format tar" in changes[0]
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


def test_a_rewritten_form_is_read_at_load_with_the_new_name_in_the_warning(tmp_path: Path) -> None:
    doc = {"calibration": {"optimizer_kwargs": {"seed": 1}, "max_iter": 5}}
    with pytest.warns(ConfigKeyRenamedWarning) as told:
        migrate_config_doc_on_load(doc, source=tmp_path / "project.toml")

    assert doc == {"calibration": {"method_options": {"seed": 1}, "max_trials": 5}}
    text = " ".join(str(warning.message) for warning in told)
    assert "optimizer_kwargs -> method_options" in text
    assert "max_iter -> max_trials" in text


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

    assert changes == [
        "calibration.outputs.seepage_network.roptim_max dropped "
        "(2 cells is validity_length = 'auto', the default)"
    ]
    output = tomllib.loads(path.read_text())["calibration"]["outputs"]["seepage_network"]
    assert "roptim_max" not in output
    assert output["observed_position_accuracy"] == "50 m"
    assert validate_calib_output(output).validity_length == "auto"


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


def test_the_ratio_bound_migrates_on_load_and_a_current_file_is_untouched() -> None:
    doc = {"calibration": {"outputs": {"net": {"support": "network", "roptim_max": 2.0}}}}
    current = {"calibration": {"outputs": {"net": {"validity_length": "150 m"}}}}

    assert migrate_config_doc_on_load(doc, source="calibration.toml")
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
            '[[simulation.process]]\nid = "flow"\ntype = "flow"\nsolvers = ["modflow_nwt"]\n',
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
    with pytest.warns(ConfigKeyRenamedWarning):
        read = load_toml_with_base_config(sibling)["calibration"]["protocol"]
    assert read["transient_method_options"] == {"chain_length": 50}
    assert "transient_max_trials" not in read


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
