"""``hmp process chain`` through a real pipe, two real jobs, one command.

The chain is only worth anything if the second job reads bytes the first one
sealed, so nothing here is faked: a subprocess runs the verb, and the test
opens the two directories afterwards with ``json`` alone.

The pair is ``terrain-delineate`` twice, the second delineating the corrected
DEM the first produced. The real pair of the campaign is delineate then fetch,
and it is asserted on the declarations in
``tests/unit/schema/test_a_chain_feeds_one_job_from_another.py``: running it
would reach four providers over the network, which is exactly what a test may
not do.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("whitebox_workflows")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEM = REPO_ROOT / "tests" / "data" / "sfr_cheze" / "dem_valley.tif"
OUTLET = {"site_id": "valley", "x": 300112.5, "y": 6701262.5}

EXIT_USAGE = 2
EXIT_CONFIG = 14

CORRECTED_DEM = "outputs/dem_corrected.tif"


def _chain_document(**overrides: object) -> dict:
    document: dict[str, object] = {
        "steps": [
            {
                "id": "delineate",
                "process": {"id": "terrain-delineate", "version": "1.0.0"},
                "inputs": {
                    "dem": {"href": str(DEM), "type": "image/tiff; application=geotiff"},
                    "outlets": [OUTLET],
                    "crs_project": "EPSG:2154",
                    "snap_distance_m": 100,
                },
            },
            {
                "id": "again",
                "process": {"id": "terrain-delineate"},
                "inputs": {
                    "outlets": [OUTLET],
                    "crs_project": "EPSG:2154",
                    "snap_distance_m": 100,
                },
                "links": [{"member": "dem", "step": "delineate", "output": "dem_corrected"}],
            },
        ]
    }
    document.update(overrides)
    return document


def _root(tmp_path: Path, document: dict | None, *, name: str = "chain") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    if document is not None:
        (root / "chain.json").write_text(json.dumps(document), encoding="utf-8")
    return root


def _hmp(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hydromodpy", *argv],
        cwd=str(REPO_ROOT),
        env=dict(os.environ, HMP_NO_PROGRESS="1"),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("process_chain")
    root = _root(tmp_path, _chain_document())
    completed = _hmp("process", "chain", "--root", str(root))
    return root, completed


def test_one_command_runs_both_jobs_and_seals_both(finished) -> None:
    root, completed = finished

    assert completed.returncode == 0, completed.stderr[-4000:]
    assert (root / "01-delineate" / "manifest.json").is_file()
    assert (root / "02-again" / "manifest.json").is_file()


def test_stdout_is_the_report_byte_for_byte(finished) -> None:
    root, completed = finished

    assert completed.stdout == (root / "chain-outcome.json").read_text(encoding="utf-8")
    document = json.loads(completed.stdout)
    assert document["status"] == "successful"
    assert [step["status"] for step in document["steps"]] == ["successful", "successful"]


def test_the_second_job_names_the_first_in_what_it_read(finished) -> None:
    """The exit gate of the phase, read off the two directories.

    Twice, and the second one is the one that matters: ``request.json`` is what
    the chain wrote, and ``inputset.json`` is what the second job says it
    consumed -- sealed, with the digest of the bytes it read.
    """
    root, _ = finished
    produced = root / "01-delineate" / CORRECTED_DEM

    request = json.loads((root / "02-again" / "request.json").read_text(encoding="utf-8"))
    assert request["inputs"]["dem"]["href"] == str(produced)

    inputset = json.loads((root / "02-again" / "inputset.json").read_text(encoding="utf-8"))
    consumed = {resource["name"]: resource for resource in inputset["resources"]}
    assert consumed["dem"]["href"] == str(produced)
    assert consumed["dem"]["sha256"]


def test_the_report_names_every_step_directory(finished) -> None:
    _, completed = finished

    document = json.loads(completed.stdout)
    assert [step["dir"] for step in document["steps"]] == ["01-delineate", "02-again"]
    assert document["steps"][1]["inputs_from"] == [
        {
            "member": "dem",
            "step": "delineate",
            "output": "dem_corrected",
            "path": f"01-delineate/{CORRECTED_DEM}",
            "type": "image/tiff; application=geotiff",
        }
    ]


def test_running_the_same_chain_again_reuses_both_jobs(finished) -> None:
    """Idempotency is the steps', not the chain's, and it composes."""
    root, _ = finished

    completed = _hmp("process", "chain", "--root", str(root))

    assert completed.returncode == 0, completed.stderr[-4000:]
    document = json.loads(completed.stdout)
    assert [step["reused"] for step in document["steps"]] == [True, True]


def test_a_directory_without_a_chain_document_is_a_usage_error(tmp_path: Path) -> None:
    root = _root(tmp_path, None, name="empty")

    completed = _hmp("process", "chain", "--root", str(root))

    assert completed.returncode == EXIT_USAGE
    assert completed.stdout == ""
    assert "chain.json" in completed.stderr


def test_a_refused_document_leaves_the_root_exactly_as_staged(tmp_path: Path) -> None:
    root = _root(
        tmp_path,
        _chain_document(steps=[{"id": "only", "process": {"id": "no-such-capability"}}]),
        name="refused",
    )

    completed = _hmp("process", "chain", "--root", str(root))

    assert completed.returncode == EXIT_CONFIG
    assert completed.stdout == ""
    assert [entry.name for entry in root.iterdir()] == ["chain.json"]


def test_a_terrain_and_a_domain_chain_into_a_sealed_geometry(tmp_path: Path) -> None:
    """The pair F7e exists for, run for real through one command.

    The mesh generator of this tree reads its vertical extent off a live
    ``Domain`` built one step after the meshing. What this asserts is that the
    same geometry is reachable as a directory a stranger can open: the
    delineation seals a corrected DEM and a catchment, and the domain seals a
    bottom, a thickness and a document naming the digest of the terrain it came
    from -- with no workspace, no catalog and no database anywhere in between.
    """
    root = _root(
        tmp_path,
        {
            "steps": [
                {
                    "id": "delineate",
                    "process": {"id": "terrain-delineate", "version": "1.0.0"},
                    "inputs": {
                        "dem": {"href": str(DEM), "type": "image/tiff; application=geotiff"},
                        "outlets": [OUTLET],
                        "crs_project": "EPSG:2154",
                        "snap_distance_m": 100,
                    },
                },
                {
                    "id": "domain",
                    "process": {"id": "domain-build", "version": "1.0.0"},
                    "inputs": {
                        "depth_model": {"kind": "constant_thickness", "thickness": 30.0},
                        "mask_layer": "watershed",
                    },
                    "links": [
                        {"member": "dem", "step": "delineate", "output": "dem_corrected"},
                        {"member": "mask", "step": "delineate", "output": "watershed_vector"},
                    ],
                },
            ]
        },
        name="terrain_to_domain",
    )

    completed = _hmp("process", "chain", "--root", str(root))

    assert completed.returncode == 0, completed.stderr[-4000:]
    assert (root / "02-domain" / "manifest.json").is_file()
    document = json.loads(
        (root / "02-domain" / "outputs" / "domain.json").read_text(encoding="utf-8")
    )
    inputset = json.loads((root / "02-domain" / "inputset.json").read_text(encoding="utf-8"))
    consumed = {resource["name"]: resource for resource in inputset["resources"]}

    assert document["layers"][0]["top"]["sha256"] == consumed["dem"]["sha256"]
    assert document["active_cells"]["mask"]["sha256"] == consumed["mask"]["sha256"]
    assert document["depth_model"] == {"kind": "constant_thickness", "thickness": 30.0}
    assert 0 < document["active_cells"]["count"] < document["active_cells"]["total"]
    assert document["statistics"]["thickness"]["min"] == 30.0
