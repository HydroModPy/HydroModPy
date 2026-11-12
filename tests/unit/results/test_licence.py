"""The licence of a run is the roll-up of the licences its ``inputs.json`` entries carry.

Each entry takes its licence from the sidecar of its file, when the run reads
it. The tables here play the roll-up, the entries a store builds from the files
a configuration declares, and the entry a loaded record gives.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.tracking.input_file import TrackedFileEntry
from hydromodpy.results.record.manifest import InputEntry
from hydromodpy.results.storage.licence import run_licence
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.workflow.steps.prepare_solver.prepare import _loaded_input_entry
from tests._helpers.run_stores import open_run_store


def _entry(variable: str = "dem", *, license: str | None = None, **fields: object) -> InputEntry:
    return InputEntry(
        variable=variable, provider="file", path=f"data/{variable}", license=license, **fields
    )


def _input(root: Path, name: str, **sidecar: object) -> Path:
    path = root / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode())
    if sidecar:
        path.with_name(path.name + ".json").write_text(json.dumps(sidecar), encoding="utf-8")
    return path


def _open(project: Path, declared: list[Path]) -> RunStore:
    store = open_run_store(project, "run", n_cells=4, crs_wkt="EPSG:2154", crs_epsg=2154)
    store.register_tracked_files(
        store.sim_id,
        [
            TrackedFileEntry(
                role=path.stem,
                category="data",
                original_path=str(path),
                canonical_path=path,
                portable=True,
            )
            for path in declared
        ],
    )
    return store


MESH = InputEntry(variable="mesh", provider="store", product="mesh", path="mesh")


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        ([], UNDETERMINED_LICENSE),
        ([_entry(license="etalab-2.0")], "etalab-2.0"),
        ([_entry("a", license="etalab-2.0"), _entry("b", license="etalab-2.0")], "etalab-2.0"),
        (
            [_entry("a", license="etalab-2.0"), _entry("b", license="ODbL-1.0")],
            "ODbL-1.0 AND etalab-2.0",
        ),
        ([_entry("a", license="etalab-2.0"), _entry("b", license=None)], UNDETERMINED_LICENSE),
        ([_entry("a", license="etalab-2.0"), _entry("b", license="  ")], UNDETERMINED_LICENSE),
        (
            [_entry("a", license="etalab-2.0"), _entry("b", license=UNDETERMINED_LICENSE)],
            UNDETERMINED_LICENSE,
        ),
        ([_entry(license="etalab-2.0"), MESH], "etalab-2.0"),
        ([MESH], UNDETERMINED_LICENSE),
    ],
    ids=[
        "no-entry",
        "one",
        "same-twice",
        "two-licences",
        "one-without-licence",
        "one-blank",
        "one-undetermined",
        "sealed-mesh-adds-nothing",
        "sealed-mesh-alone",
    ],
)
def test_the_run_states_the_roll_up_of_its_entries(
    entries: list[InputEntry], expected: str
) -> None:
    assert run_licence(entries) == expected


def test_one_unknown_input_leaves_the_run_undetermined(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    dem = _input(project, "dem.tif", source="ign_geoplateforme_dem", license="etalab-2.0")
    recharge = _input(project, "recharge.csv", source="file", license=UNDETERMINED_LICENSE)
    with _open(project, [dem, recharge]) as store:
        assert store.licence() == UNDETERMINED_LICENSE


def test_a_declared_file_a_loaded_record_names_enters_once_with_the_licence_of_the_record(
    tmp_path: Path,
) -> None:
    project = tmp_path / "demo"
    dem = _input(project, "dem.tif", source="file", license="etalab-2.0")
    with _open(project, [dem]) as store:
        (declared,) = store.inputs()
        store.record_input(
            store.sim_id,
            InputEntry(
                variable="catchment:dem",
                provider="file",
                path=declared.path,
                license="CC-BY-4.0",
            ),
        )
        (entry,) = store.inputs()
        assert entry.license == "CC-BY-4.0"
        assert store.licence() == "CC-BY-4.0"


def test_a_declared_folder_and_a_missing_file_are_not_inputs(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    folder = project / "data" / "tiles"
    folder.mkdir(parents=True)
    missing = project / "data" / "gone.csv"
    with _open(project, [folder, missing]) as store:
        assert store.inputs() == []


def test_a_loaded_record_with_no_file_is_undetermined() -> None:
    item = SimpleNamespace(
        scope="catchment", variable="flow", record=SimpleNamespace(source="hubeau")
    )

    entry = _loaded_input_entry(item, source_path=None, sha256=None, anchor=None)

    assert entry.license == UNDETERMINED_LICENSE
