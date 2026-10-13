"""A configuration stored before ``[mesh]`` is translated, not refused.

A run keeps its whole configuration. The sections ``[mesh_catchment]`` and
``[mesh_input]`` and the ``planar`` and ``grid_dual`` keys of both MODFLOW
backends were replaced by ``[mesh]``; the stored copy follows the translation
table, so a sealed run can still be resumed, rerun or compared.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.stored_config_migration import (
    migrate_stored_config,
    translate_retired_mesh_sections,
)
from hydromodpy.spatial.mesh.config import MeshConfig

_FIXTURES = Path(__file__).parent / "fixtures" / "stored_e611edf79"


def _doc(solver: str = "modflow6", **sections: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "workflow": {"mode": "simulation"},
        "workspace": {"project_root": "."},
        "geographic": {"source_mode": "synthetic"},
        "simulation": {"process": [{"id": "flow_main", "type": "flow", "solvers": [solver]}]},
    }
    doc.update(sections)
    return doc


def _catchment(**overrides: Any) -> dict[str, Any]:
    table: dict[str, Any] = {
        "constraints_mode": "geology_rivers",
        "cache": True,
        "figures_enabled": False,
        "zone_meshing": {
            "algorithm": "frontal",
            "global_size": 150.0,
            "min_size": 20.0,
            "refine_interfaces": True,
            "interface_size": 25.0,
            "interface_distance": 300.0,
        },
        "watershed_boundary": {
            "enabled": True,
            "outside_coarsening": {
                "enabled": True,
                "size_factor": 3.0,
                "transition_distance": 400.0,
            },
        },
        "lake_refinement": {"enabled": False, "cell_size": 40.0},
        "refinement_zone": [],
    }
    table.update(overrides)
    return table


def test_a_catchment_mesh_becomes_a_voronoi_mesh_with_its_sizes() -> None:
    doc = _doc(mesh_catchment=_catchment())
    changes = translate_retired_mesh_sections(doc)
    assert "mesh_catchment" not in doc
    assert doc["mesh"] == {
        "engine": "voronoi",
        "cell_size": 150.0,
        "river_cell_size": 25.0,
        "river_band": 300.0,
        "triangle": {"algorithm": "frontal"},
        "families": {"watershed_boundary": "face"},
        "outside_factor": 3.0,
        "transition_distance": 400.0,
    }
    assert changes == ["mesh_catchment -> mesh (engine 'voronoi')"]
    assert MeshConfig.model_validate(doc["mesh"]).engine == "voronoi"


@pytest.mark.parametrize(
    ("mode", "families"),
    [
        ("rivers_only", {"geology": "none"}),
        ("geology_only", {"rivers": "none"}),
        ("geology_rivers", {}),
    ],
)
def test_the_constraints_mode_becomes_the_families(mode: str, families: dict[str, str]) -> None:
    table = _catchment(constraints_mode=mode, watershed_boundary={"enabled": False})
    doc = _doc(mesh_catchment=table)
    translate_retired_mesh_sections(doc)
    assert doc["mesh"].get("families", {}) == families
    assert doc["mesh"]["outside_factor"] == 1.0


def test_the_interface_sizes_follow_only_rivers_that_were_constrained() -> None:
    doc = _doc(mesh_catchment=_catchment(constraints_mode="geology_only"))
    translate_retired_mesh_sections(doc)
    assert "river_cell_size" not in doc["mesh"]
    assert "river_band" not in doc["mesh"]


def test_an_enabled_lake_refinement_and_the_zones_are_kept() -> None:
    table = _catchment(
        lake_refinement={"enabled": True, "cell_size": 30.0},
        refinement_zone=[{"path": "zones.gpkg", "cell_size": 20.0}],
    )
    doc = _doc(mesh_catchment=table)
    translate_retired_mesh_sections(doc)
    assert doc["mesh"]["lake_refinement"]["cell_size"] == 30.0
    assert doc["mesh"]["refinement_zone"] == [{"path": "zones.gpkg", "cell_size": 20.0}]
    assert MeshConfig.model_validate(doc["mesh"]).lake_refinement is not None


def test_grid_dual_triangle_gives_the_triangle_engine_and_the_keys_go() -> None:
    doc = _doc(
        mesh_catchment=_catchment(),
        modflow6={"sgrid": {"grid_dual": "triangle", "planar": {"mode": "keep_native"}}},
        modflownwt={"sgrid": {"grid_dual": "voronoi", "planar": {"mode": "keep_native"}}},
    )
    translate_retired_mesh_sections(doc)
    assert doc["mesh"]["engine"] == "triangle"
    assert doc["modflow6"]["sgrid"] == {}
    assert doc["modflownwt"]["sgrid"] == {}


def test_a_boussinesq_run_gets_the_triangle_engine() -> None:
    doc = _doc("boussinesq", mesh_catchment=_catchment())
    translate_retired_mesh_sections(doc)
    assert doc["mesh"]["engine"] == "triangle"


def test_an_external_mesh_becomes_the_triangulation_to_read() -> None:
    doc = _doc(mesh_input={"mesh_path": "mesh/catchment.msh", "bundle_dir": "bundle"})
    translate_retired_mesh_sections(doc)
    assert doc["mesh"] == {
        "engine": "voronoi",
        "triangle": {"path": "mesh/catchment.msh"},
        "voronoi": {"seeds": "triangulation"},
    }
    assert MeshConfig.model_validate(doc["mesh"]).triangle.path == Path("mesh/catchment.msh")


def test_an_external_mesh_of_a_triangle_run_reads_no_generators() -> None:
    doc = _doc("boussinesq", mesh_input={"mesh_path": "m.msh"})
    translate_retired_mesh_sections(doc)
    assert doc["mesh"] == {"engine": "triangle", "triangle": {"path": "m.msh"}}


def test_a_resampled_grid_keeps_its_exact_shape() -> None:
    planar = {"mode": "resample_to_shape", "nx": 80, "ny": 60, "resampling": "bilinear"}
    doc = _doc(modflow6={"sgrid": {"planar": planar, "grid_dual": "voronoi"}})
    changes = translate_retired_mesh_sections(doc)
    assert doc["mesh"] == {"regular": {"shape": [60, 80]}}
    assert MeshConfig.model_validate(doc["mesh"]).regular.shape == (60, 80)
    assert any("mesh.regular" in line for line in changes)
    assert "planar" not in doc["modflow6"]["sgrid"]


def test_the_planar_key_of_the_solver_that_ran_is_the_one_read() -> None:
    doc = _doc(
        "modflow_nwt",
        modflow6={"sgrid": {"planar": {"mode": "resample_to_shape", "nx": 5, "ny": 5}}},
        modflownwt={"sgrid": {"planar": {"mode": "resample_to_shape", "nx": 40, "ny": 5}}},
    )
    translate_retired_mesh_sections(doc)
    assert doc["mesh"] == {"regular": {"shape": [5, 40]}}


def test_a_native_grid_translates_to_no_mesh_section() -> None:
    doc = _doc(modflow6={"sgrid": {"planar": {"mode": "keep_native"}, "grid_dual": "voronoi"}})
    translate_retired_mesh_sections(doc)
    assert "mesh" not in doc


def test_a_catchment_mesh_next_to_nwt_is_dropped_because_nwt_never_read_it() -> None:
    doc = _doc("modflow_nwt", mesh_catchment=_catchment())
    changes = translate_retired_mesh_sections(doc)
    assert "mesh" not in doc
    assert "modflow_nwt never read it" in changes[0]


def test_null_tables_are_dropped() -> None:
    doc = _doc(mesh_catchment=None, mesh_input=None)
    changes = translate_retired_mesh_sections(doc)
    assert "mesh_catchment" not in doc
    assert "mesh_input" not in doc
    assert len(changes) == 2


def test_a_translated_document_is_current() -> None:
    doc = _doc(mesh_catchment=_catchment(), modflow6={"sgrid": {"grid_dual": "voronoi"}})
    translate_retired_mesh_sections(doc)
    assert translate_retired_mesh_sections(doc) == []


def test_an_overlay_is_translated_against_the_solver_of_the_root() -> None:
    doc = _doc(
        "boussinesq",
        comparison={
            "simulation": [
                {
                    "id": "child",
                    "mesh_mode": "mesh_catchment",
                    "overlay": {"mesh_catchment": {"zone_meshing": {"global_size": 90.0}}},
                }
            ]
        },
    )
    translate_retired_mesh_sections(doc)
    child = doc["comparison"]["simulation"][0]
    assert child["mesh_mode"] == "triangle"
    assert child["overlay"]["mesh"]["engine"] == "triangle"
    assert child["overlay"]["mesh"]["cell_size"] == 90.0


def test_a_comparison_child_on_the_dual_gets_the_voronoi_tag() -> None:
    child = {"id": "a", "mesh_mode": "mesh_input", "solver": "modflow6"}
    doc = _doc(comparison={"simulation": [child]})
    translate_retired_mesh_sections(doc)
    assert doc["comparison"]["simulation"][0]["mesh_mode"] == "voronoi"


def test_the_stored_migration_runs_it_and_logs_one_line(caplog: pytest.LogCaptureFixture) -> None:
    doc = _doc(mesh_catchment=_catchment())
    with caplog.at_level("INFO", logger="hydromodpy"):
        migrated = migrate_stored_config(doc, source="test")
    assert migrated["mesh"]["engine"] == "voronoi"
    assert "mesh_catchment" not in migrated
    lines = [r.getMessage() for r in caplog.records if "migrated" in r.msg]
    assert len(lines) == 1
    assert "mesh_catchment -> mesh" in lines[0]
    assert "mesh_catchment" in doc


def test_the_snapshot_of_the_earlier_version_still_reloads() -> None:
    snapshot = json.loads((_FIXTURES / "snapshot_modflow_nwt.json").read_text(encoding="utf-8"))
    assert "mesh_catchment" in snapshot and "grid_dual" in snapshot["modflownwt"]["sgrid"]
    before = copy.deepcopy(snapshot)

    cfg = HydroModPyConfig.from_snapshot(snapshot)

    assert snapshot == before
    assert cfg.mesh is None
    assert cfg.solver.backend_name == "modflow_nwt"
