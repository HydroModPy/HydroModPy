"""The TOML migration a config goes through on load, before validation.

Every case reads its document as the loader does (``tomllib``) and runs
``migrate_config_doc`` on it in memory; nothing writes a file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.config.config_migration import (
    migrate_config_doc,
    migrate_config_doc_on_load,
)


def _migrated(body: str) -> tuple[list[str], dict[str, Any]]:
    """Return the changes and the document the migration makes of *body*."""
    doc = tomllib.loads(body)
    changes = migrate_config_doc(doc)
    return changes, doc


def test_migrates_on_collision_and_run_id() -> None:
    changes, doc = _migrated(
        "# header\n[simulation]\n# the run name\n"
        'run_id = "cheze_baseline"\non_collision = "replace"\n'
        'description = "weekly"\n',
    )
    assert any("on_collision -> if_exists" in c for c in changes)
    assert any("run_id -> name" in c for c in changes)

    parsed = doc["simulation"]
    assert "on_collision" not in parsed
    assert parsed["if_exists"] == "version"
    assert "run_id" not in parsed
    assert parsed["name"] == "cheze_baseline"
    assert parsed["description"] == "weekly"


def test_run_id_dropped_when_name_already_set() -> None:
    changes, doc = _migrated('[simulation]\nname = "kept"\nrun_id = "ignored"\n')
    assert any("name already set" in c for c in changes)
    parsed = doc["simulation"]
    assert parsed["name"] == "kept"
    assert "run_id" not in parsed


def test_idempotent_and_noop_returns_empty() -> None:
    changes, _ = _migrated('[simulation]\nname = "modern"\nif_exists = "version"\n')
    assert changes == []


def test_promotes_export_to_top_level() -> None:
    changes, parsed = _migrated(
        '[simulation]\nname = "cheze"\n\n'
        "[simulation.results.export]\ncsv_timeseries = true\ngeotiff = true\n\n"
        '[[simulation.results.export.artifacts]]\nvar = "head"\ndest = "h.tif"\n',
    )
    assert any("simulation.results.export -> [export]" in c for c in changes)

    assert parsed["export"] == [
        {"variables": "all", "format": "csv"},
        {"variables": ["head"], "format": "geotiff", "time": "last"},
        {"variables": "head", "file": "h.tif"},
    ]
    # the buried section is gone
    assert "export" not in parsed.get("simulation", {}).get("results", {})


def test_export_promotion_skips_when_top_level_exists() -> None:
    changes, parsed = _migrated(
        "[export]\nnetcdf = true\n\n[simulation.results.export]\ncsv_timeseries = false\n",
    )
    assert any("top-level [export] already set" in c for c in changes)
    assert parsed["export"] == [{"variables": ["head"], "format": "netcdf", "time": "last"}]
    assert "export" not in parsed.get("simulation", {}).get("results", {})


def test_drops_the_two_options_that_never_drove_anything() -> None:
    changes, parsed = _migrated(
        '[simulation]\nname = "cheze"\n\n'
        '[simulation.results]\nsolver_scratch = ".hmp/scratch"\nkeep_solver_files = true\n\n'
        "[simulation.results.persistence]\nsave_lock = true\nsave_zarr = true\n\n"
        "[persistence]\nsave_lock = false\n\n"
        "[calibration.persistence]\nsave_lock = true\n",
    )
    assert any("solver_scratch dropped" in c for c in changes)
    assert sum("save_lock dropped" in c for c in changes) == 3

    results = parsed["simulation"]["results"]
    assert "solver_scratch" not in results
    assert results["keep_solver_files"] is True
    assert "save_lock" not in results["persistence"]
    assert results["persistence"]["save_zarr"] is True
    assert "save_lock" not in parsed["persistence"]
    assert "save_lock" not in parsed["calibration"]["persistence"]
    assert migrate_config_doc(parsed) == []


def test_flattens_a_family_keyed_boundary() -> None:
    """``[flow.bc.<family>.<id>]`` becomes ``[flow.bc.<id>]`` carrying its kind."""
    changes, parsed = _migrated(
        "[flow.bc.dirichlet.west_side]\nvalue = 5.0\n\n"
        '[flow.bc.cauchy.drainage]\nvalue = "1e-6 m2/s"\n',
    )
    bc = parsed["flow"]["bc"]

    assert "dirichlet" not in bc
    assert "cauchy" not in bc
    assert bc["west_side"] == {"value": 5.0, "kind": "dirichlet"}
    assert bc["drainage"] == {"value": "1e-6 m2/s", "kind": "cauchy"}
    assert len(changes) == 2
    assert migrate_config_doc(parsed) == []


def test_a_flat_entry_already_there_wins_over_the_nested_one() -> None:
    """A flat mapping cannot hold the same id twice, so the nested one is dropped."""
    changes, parsed = _migrated(
        "[flow.bc.west_side]\nvalue = 9.0\n\n[flow.bc.dirichlet.west_side]\nvalue = 1.0\n",
    )
    bc = parsed["flow"]["bc"]

    assert bc["west_side"] == {"value": 9.0}
    assert "dirichlet" not in bc
    assert changes == ["flow.bc.dirichlet.west_side dropped (flow.bc.west_side already set)"]


def test_a_file_with_no_flow_section_is_left_alone() -> None:
    changes, _ = _migrated('[simulation]\nname = "plain"\n')
    assert changes == []


def test_drops_both_solver_time_grids_at_the_root() -> None:
    changes, parsed = _migrated(
        "[modflow6]\nrelax_steady = true\n\n[modflow6.tgrid]\nnper = 1\n\n"
        '[modflownwt]\n\n[modflownwt.tgrid]\nitmuni = "days"\nnper = 1\n',
    )

    assert any("modflow6.tgrid dropped" in c for c in changes)
    assert any("modflownwt.tgrid dropped" in c for c in changes)
    assert "tgrid" not in parsed["modflow6"]
    assert "tgrid" not in parsed["modflownwt"]
    assert parsed["modflow6"]["relax_steady"] is True


def test_expands_the_export_variables_boolean_table() -> None:
    changes, parsed = _migrated(
        "[export]\ngeotiff = true\n[export.variables]\nhead = true\nconcentration = false\n"
        "derived = true\nbudget = true\npathlines = true\n",
    )
    assert any("export.variables (boolean table) -> list" in c for c in changes)

    (block,) = parsed["export"]
    assert block["variables"] == [
        "head",
        "watertable_elevation",
        "watertable_depth",
        "seepage_mask",
    ]
    assert migrate_config_doc(parsed) == []


def test_export_variables_all_off_is_carried_as_an_empty_list() -> None:
    """The request keeps what the file said; the loader then refuses an empty list."""
    changes, parsed = _migrated(
        "[export]\nnetcdf = true\n[export.variables]\nhead = false\nconcentration = false\n",
    )
    assert any("-> list []" in c for c in changes)
    assert parsed["export"][0]["variables"] == []


def test_renames_export_times_to_time() -> None:
    changes, parsed = _migrated('[export]\ngeotiff = true\ntimes = "first"\n')
    assert any("export.times -> export.time" in c for c in changes)

    (block,) = parsed["export"]
    assert block["time"] == "first"
    assert "times" not in block
    assert migrate_config_doc(parsed) == []


def test_export_times_dropped_when_time_already_set() -> None:
    changes, parsed = _migrated('[export]\nnetcdf = true\ntime = "all"\ntimes = "last"\n')
    assert any("export.time already set" in c for c in changes)
    (block,) = parsed["export"]
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


def test_the_requests_of_a_migrated_table_load() -> None:
    """What the migration writes is what the model reads: the round trip holds."""
    from hydromodpy.core.config_kit.export_spec import ExportFormat, load_export_requests

    _, parsed = _migrated(
        "[export]\ngeotiff = true\ncsv_timeseries = true\ntime = 33\n"
        'variables = ["head", "watertable_depth"]\n\n'
        '[[export.artifacts]]\nvar = ["head", "watertable_depth"]\ndest = "fields.nc"\n'
        'time = "all"\n',
    )

    requests = load_export_requests(parsed["export"])

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
    caplog: pytest.LogCaptureFixture,
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


def test_migrate_config_doc_on_load_migrates_in_memory_and_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    doc = tomllib.loads(
        '[export]\ngeotiff = true\ntimes = "last"\n[export.variables]\nhead = true\n'
    )
    with caplog.at_level("INFO"):
        changes = migrate_config_doc_on_load(doc, source="run/config.toml")

    assert changes == [
        "export.variables (boolean table) -> list ['head']",
        "export.times -> export.time ('last')",
        "[export] toggles and artifacts -> 1 [[export]] block(s) (geotiff)",
    ]
    assert doc["export"] == [{"variables": ["head"], "format": "geotiff", "time": "last"}]

    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert "run/config.toml" in message
    assert "3 legacy key" in message
    assert "rename them in run/config.toml" in message
    assert "hmp doctor" not in message


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


def test_renames_a_figure_timestep_to_time() -> None:
    changes, parsed = _migrated(
        '[display]\nfigures = ["seepage_map"]\n\n'
        "[display.overrides.seepage_map]\ntimestep = 33 # October 2002\n\n"
        '[display.overrides.cross_section]\norientation = "sn"\n',
    )

    assert changes == [
        "display.overrides.seepage_map.timestep -> display.overrides.seepage_map.time (33)"
    ]
    overrides = parsed["display"]["overrides"]
    assert overrides == {"seepage_map": {"time": 33}, "cross_section": {"orientation": "sn"}}
    assert migrate_config_doc(parsed) == []


def test_a_figure_that_says_both_is_left_for_the_loader_to_refuse() -> None:
    """Both spellings may name different instants: picking one would hide it."""
    doc = {"display": {"overrides": {"seepage_map": {"timestep": 33, "time": "2002-10-15"}}}}
    phase = {"display.overrides.seepage_map.timestep": 0, "display.overrides.seepage_map.time": 1}
    doc["calibration"] = {"phases": [{"overrides": dict(phase)}]}

    assert migrate_config_doc(doc) == []
    assert doc["display"]["overrides"]["seepage_map"] == {"timestep": 33, "time": "2002-10-15"}
    assert doc["calibration"]["phases"][0]["overrides"] == phase


def test_renames_the_dotted_timestep_a_calibration_phase_overrides() -> None:
    changes, parsed = _migrated(
        '[[calibration.phases]]\nname = "steady"\n\n'
        "[calibration.phases.overrides]\n"
        '"display.overrides.seepage_map.timestep" = 0\n'
        '"display.overrides.cross_section.timestep" = 0\n'
        '"flow.flow_regime" = "steady"\n',
    )

    assert changes == [
        'calibration.phases[0].overrides."display.overrides.seepage_map.timestep" -> '
        '"display.overrides.seepage_map.time"',
        'calibration.phases[0].overrides."display.overrides.cross_section.timestep" -> '
        '"display.overrides.cross_section.time"',
    ]
    overrides = parsed["calibration"]["phases"][0]["overrides"]
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


def test_moves_the_bottom_path_to_the_substratum_and_leaves_the_depth_model() -> None:
    changes, parsed = _migrated(
        '[geographic]\nbottom_path = "data/bottom.tif"\n\n'
        '[domain.depth_model]\nkind = "constant_thickness"\nthickness = "30 m"\n',
    )

    assert any("geographic.bottom_path -> [[data.substratum.sources]]" in c for c in changes)
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


def test_the_paper_ratio_bound_is_dropped_and_auto_replaces_it() -> None:
    from hydromodpy.calibration.config import validate_calib_output

    changes, parsed = _migrated(_NETWORK_OUTPUT.format(value="2.0"))

    assert changes == [
        "calibration.outputs.seepage_network.roptim_max dropped "
        "(2 cells is validity_length = 'auto', the default)"
    ]
    output = parsed["calibration"]["outputs"]["seepage_network"]
    assert "roptim_max" not in output
    assert output["observed_position_accuracy"] == "50 m"
    assert validate_calib_output(output).validity_length == "auto"


def test_an_integer_two_is_the_paper_bound_too() -> None:
    doc = {"calibration": {"outputs": {"net": {"support": "network", "roptim_max": 2}}}}

    assert len(migrate_config_doc(doc)) == 1
    assert "roptim_max" not in doc["calibration"]["outputs"]["net"]


def test_another_ratio_bound_is_refused_with_the_length_to_write() -> None:
    with pytest.raises(ValueError, match="validity_length") as raised:
        _migrated(_NETWORK_OUTPUT.format(value="3.0"))

    assert "roptim_max = 3 has no exact equivalent" in str(raised.value)


def test_the_ratio_bound_migrates_on_load_and_a_current_file_is_untouched() -> None:
    doc = {"calibration": {"outputs": {"net": {"support": "network", "roptim_max": 2.0}}}}
    current = {"calibration": {"outputs": {"net": {"validity_length": "150 m"}}}}

    assert migrate_config_doc_on_load(doc, source="calibration.toml")
    assert migrate_config_doc(current) == []
    assert current["calibration"]["outputs"]["net"] == {"validity_length": "150 m"}
