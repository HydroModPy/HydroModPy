"""A mesh description is read only when it still describes something.

The document lets a resume reload a mesh instead of regenerating it, and Gmsh
is not reproducible run to run, so a description that is trusted when it should
not be does not cost time, it changes every number computed on the mesh. Every
way it can be wrong is therefore a clean miss, which sends the caller back to a
full re-mesh - what it would have done anyway.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from hydromodpy.spatial.mesh.runtime_description import (
    DESCRIPTION_FILENAME,
    SCHEMA_VERSION,
    mesh_artifact_paths,
    mesh_description_path,
    read_mesh_description,
    write_mesh_description,
)


def _mesh_tree(root: Path) -> dict[str, object]:
    """Write a mesh and an exchange bundle, and return the summary naming them."""
    mesh_dir = root / "mesh"
    bundle = mesh_dir / "mesh_catchment_bundle"
    bundle.mkdir(parents=True)
    (mesh_dir / "mesh_catchment.msh").write_text("$MeshFormat\n", encoding="utf-8")
    (bundle / "nodes.csv").write_text("id,x,y\n", encoding="utf-8")
    (bundle / "cells.csv").write_text("id,nodes\n", encoding="utf-8")
    return {
        "output_mesh": str(mesh_dir / "mesh_catchment.msh"),
        "output_exchange_bundle_dir": str(bundle),
        "n_cells": 400,
        "algorithm": "delaunay",
    }


def test_a_written_description_reads_back_unchanged(tmp_path: Path) -> None:
    """The summary is the document, so the round trip has to be exact."""
    summary = _mesh_tree(tmp_path)

    write_mesh_description(tmp_path / "mesh", summary)

    assert read_mesh_description(tmp_path / "mesh") == summary


def test_a_copied_project_reads_its_own_mesh(tmp_path: Path) -> None:
    """The description describes the tree it sits in, not the one that wrote it.

    Copying a project and keeping the original is how a template, an example
    and a multi-catchment iteration all start. A description storing absolute
    paths would send every run of the copy to the original's mesh, on a fresh
    run as much as on a resume, and the copy's own mesh would never be read.
    """
    summary = _mesh_tree(tmp_path / "source")
    write_mesh_description(tmp_path / "source" / "mesh", summary)
    shutil.copytree(tmp_path / "source", tmp_path / "copy")

    read = read_mesh_description(tmp_path / "copy" / "mesh")

    assert read is not None
    assert Path(str(read["output_mesh"])) == tmp_path / "copy" / "mesh" / "mesh_catchment.msh"
    assert (
        Path(str(read["output_exchange_bundle_dir"]))
        == tmp_path / "copy" / "mesh" / "mesh_catchment_bundle"
    )


def test_a_mesh_outside_the_directory_keeps_its_absolute_path(tmp_path: Path) -> None:
    """An external mesh is named where it is, not guessed under the project."""
    external = tmp_path / "elsewhere" / "imported.msh"
    external.parent.mkdir(parents=True)
    external.write_text("$MeshFormat\n", encoding="utf-8")
    mesh_dir = tmp_path / "mesh"
    mesh_dir.mkdir()

    write_mesh_description(mesh_dir, {"output_mesh": str(external)})

    read = read_mesh_description(mesh_dir)
    assert read is not None
    assert Path(str(read["output_mesh"])) == external


def test_a_description_of_another_schema_is_a_miss(tmp_path: Path) -> None:
    """A future or past document is not guessed at."""
    summary = _mesh_tree(tmp_path)
    path = mesh_description_path(tmp_path / "mesh")
    path.write_text(
        json.dumps({"schema": "hydromodpy.mesh_runtime.v0", "mesh_summary": summary}),
        encoding="utf-8",
    )

    assert read_mesh_description(tmp_path / "mesh") is None


def test_a_description_naming_a_mesh_that_is_gone_is_a_miss(tmp_path: Path) -> None:
    """The document outliving its mesh is the case that would load nothing."""
    summary = _mesh_tree(tmp_path)
    write_mesh_description(tmp_path / "mesh", summary)
    Path(str(summary["output_mesh"])).unlink()

    assert read_mesh_description(tmp_path / "mesh") is None


def test_an_unreadable_description_is_a_miss(tmp_path: Path) -> None:
    """Truncated JSON is what an interrupted write leaves."""
    _mesh_tree(tmp_path)
    mesh_description_path(tmp_path / "mesh").write_text('{"schema":', encoding="utf-8")

    assert read_mesh_description(tmp_path / "mesh") is None


def test_the_declaration_names_every_file_a_rebuild_reads(tmp_path: Path) -> None:
    """The mesh, the whole bundle, and the description that says they belong together."""
    summary = _mesh_tree(tmp_path)
    write_mesh_description(tmp_path / "mesh", summary)

    declared = mesh_artifact_paths(summary, tmp_path / "mesh")

    names = [path.name for path in declared]
    assert names[0] == DESCRIPTION_FILENAME, "the description is not declared first"
    assert set(names) == {
        DESCRIPTION_FILENAME,
        "mesh_catchment.msh",
        "nodes.csv",
        "cells.csv",
    }
    assert all(path.is_file() for path in declared)


def test_a_step_that_meshed_nothing_declares_nothing(tmp_path: Path) -> None:
    """No ``[mesh_catchment]`` and no ``[mesh_input]`` leaves no summary at all."""
    assert mesh_artifact_paths(None, tmp_path / "mesh") == ()


def test_the_schema_version_is_carried_by_the_document(tmp_path: Path) -> None:
    """A reader that never sees the version cannot refuse an old one."""
    summary = _mesh_tree(tmp_path)

    path = write_mesh_description(tmp_path / "mesh", summary)

    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == SCHEMA_VERSION
