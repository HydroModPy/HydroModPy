"""Tests for the one-shot ``hmp doctor --fix-config`` TOML rewriter."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hydromodpy.config.config_migration import fix_config_file


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
    assert parsed["if_exists"] == "replace"
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
    assert "export" in parsed
    assert parsed["export"]["csv_timeseries"] is True
    assert parsed["export"]["geotiff"] is True
    assert parsed["export"]["artifacts"][0]["var"] == "head"
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
    assert parsed["export"]["netcdf"] is True
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


def test_flattens_the_overlay_of_every_comparison_and_testbed_entry(tmp_path: Path) -> None:
    """A comparison or testbed file patches flow per case, under ``overlay``.

    Those overlays reach the same loader and are refused by the same rule, so a
    migration that only looked at the root ``[flow]`` left the file broken and
    reported nothing to fix.
    """
    path = _write(
        tmp_path,
        '[[comparison.simulation]]\nid = "low_k"\n'
        '[comparison.simulation.overlay.flow.bc.cauchy.drainage]\nvalue = "1e-7 m2/s"\n\n'
        '[[comparison.simulation]]\nid = "high_k"\n'
        '[comparison.simulation.overlay.flow.bc.robin.drainage]\nvalue = "3e-3 m2/s"\n\n'
        '[[testbed.case]]\nid = "patchy"\n'
        "[testbed.case.overlay.flow.bc.dirichlet.east_side]\nvalue = 2.5\n",
    )

    changes = fix_config_file(path)
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    simulations = parsed["comparison"]["simulation"]
    case = parsed["testbed"]["case"][0]

    first = simulations[0]["overlay"]["flow"]["bc"]
    assert "cauchy" not in first
    assert first["drainage"] == {"value": "1e-7 m2/s", "kind": "cauchy"}

    # A robin drainage departs from the registry default, so the kind it gains
    # is the whole point: dropping it would silently make it a cauchy one.
    second = simulations[1]["overlay"]["flow"]["bc"]
    assert "robin" not in second
    assert second["drainage"] == {"value": "3e-3 m2/s", "kind": "robin"}

    overlay_bc = case["overlay"]["flow"]["bc"]
    assert "dirichlet" not in overlay_bc
    assert overlay_bc["east_side"] == {"value": 2.5, "kind": "dirichlet"}

    assert len(changes) == 3
    assert all("overlay.flow.bc" in change for change in changes)
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
