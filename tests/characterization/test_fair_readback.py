"""The three declarations a produced run makes and does not honour.

Every test here is ``xfail(strict=True)``: it asserts the behaviour the run
*claims*, which today it does not have. They are written now, before anything
structural moves, so that the day the claim becomes true the suite says so
instead of staying quietly green. A strict xfail that starts passing is a
failure, which is the point: nobody has to remember to come back.

Findings pinned, from ``red-fair.md``:

``test_a_stranger_opens_the_field_store_with_xarray``
    F1. ``xr.open_zarr`` raises on every run ever written because no array
    carries ``dimension_names``, and ``coordinates`` names two arrays that do
    not exist. Repaired by F1.
``test_the_field_store_metadata_is_valid_json``
    F2, F3. Bare ``NaN`` tokens make ``zarr.json`` invalid JSON, and the repair
    must not re-encode them as strings, which would break CF typing.
``test_the_run_declares_a_derived_identity``
    B1, B4, B5, C1, D1. The licence is a Python literal, the creator is a Unix
    account name, the temporal extent is the moment of execution, ``crs_wkt``
    holds no WKT and ``duration_s`` contradicts the timestamps around it.
    Repaired by F1.

Phase F1 turned all three green; they stay here as plain tests.
"""

from __future__ import annotations

import getpass
import json
import math
import os
import tomllib
from datetime import datetime
from pathlib import Path

import zarr

from tests.characterization.conftest import ProducedRun

_WKT_PREFIXES = ("PROJCRS", "GEOGCRS", "PROJCS", "GEOGCS", "COMPOUNDCRS", "BOUNDCRS")


def _zarr_arrays(store: Path) -> dict[str, zarr.Array]:
    """Return every array of a store, keyed by its path inside the store."""

    def walk(group: zarr.Group, prefix: str = "") -> dict[str, zarr.Array]:
        found: dict[str, zarr.Array] = {}
        for name, member in group.members():
            path = f"{prefix}/{name}" if prefix else name
            if isinstance(member, zarr.Array):
                found[path] = member
            else:
                found.update(walk(member, path))
        return found

    return walk(zarr.open_group(str(store), mode="r"))


def _workspace_license(workspace: Path) -> str | None:
    """Return the licence the workspace declares, or None when it declares none."""
    manifest = workspace / "workspace.toml"
    if not manifest.is_file():
        return None
    payload = tomllib.loads(manifest.read_text(encoding="utf-8"))
    declared = payload.get("workspace", {}).get("license")
    return str(declared) if declared else None


def _unix_account_names() -> set[str]:
    """Return every name this machine would answer for the current account."""
    names = {os.environ.get("USER"), os.environ.get("LOGNAME"), os.environ.get("USERNAME")}
    try:
        names.add(os.getlogin())
    except OSError:
        pass
    try:
        names.add(getpass.getuser())
    except Exception:  # getpass has no account to report in a bare container
        pass
    return {name for name in names if name}


def test_a_stranger_opens_the_field_store_with_xarray(produced_run: ProducedRun) -> None:
    """``xr.open_zarr`` opens the store and every axis has a name."""
    import xarray as xr

    dataset = xr.open_zarr(produced_run.field_store)
    assert "head" in dataset.variables, f"no head variable, got {sorted(dataset.variables)}"

    arrays = _zarr_arrays(produced_run.field_store)
    # A 0-d array (the CF grid mapping, the UGRID topology) has no axis to name,
    # and Zarr stores an empty ``dimension_names`` as no names at all.
    undeclared = sorted(
        name
        for name, array in arrays.items()
        if array.ndim and len(array.metadata.dimension_names or ()) != array.ndim
    )
    assert not undeclared, f"arrays without dimension_names: {undeclared}"

    missing_references: list[str] = []
    for name, array in arrays.items():
        attrs = dict(array.attrs)
        for referenced in str(attrs.get("coordinates", "")).split():
            if referenced not in arrays:
                missing_references.append(f"{name}.coordinates -> {referenced}")
        grid_mapping = attrs.get("grid_mapping")
        if grid_mapping and str(grid_mapping) not in arrays:
            missing_references.append(f"{name}.grid_mapping -> {grid_mapping}")
    assert not missing_references, f"attributes naming absent arrays: {missing_references}"


def test_the_field_store_metadata_is_valid_json(produced_run: ProducedRun) -> None:
    """Every ``zarr.json`` parses under RFC 8259, and no fill value is a string."""

    def reject_constant(token: str) -> float:
        raise ValueError(f"bare {token} token")

    invalid: list[str] = []
    for path in sorted(produced_run.field_store.rglob("zarr.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
        except ValueError as exc:
            invalid.append(f"{path.relative_to(produced_run.field_store)}: {exc}")
    assert not invalid, f"invalid JSON: {invalid}"

    stringly_typed: list[str] = []
    for name, array in _zarr_arrays(produced_run.field_store).items():
        for key in ("_FillValue", "missing_value"):
            value = dict(array.attrs).get(key)
            if isinstance(value, str):
                stringly_typed.append(f"{name}.{key} = {value!r}")
    assert not stringly_typed, f"CF attribute typed as a string: {stringly_typed}"


def test_the_two_writers_of_a_run_declare_one_licence(produced_run: ProducedRun) -> None:
    """The field store and every table of one run agree on the terms of reuse.

    ``fields.zarr`` and ``tables.parquet`` are written by two different code
    paths, and each carried its own licence literal. A deposit whose two halves
    state different terms states none (red-fair D1/D3).
    """
    import pyarrow.parquet as pq

    declared = dict(zarr.open_group(str(produced_run.field_store), mode="r").attrs)["license"]
    disagreeing: list[str] = []
    for table in sorted(produced_run.tables.glob("*.parquet")):
        metadata = pq.read_schema(table).metadata or {}
        value = metadata.get(b"license")
        if value is not None and value.decode("utf-8") != declared:
            disagreeing.append(f"{table.name}: {value.decode('utf-8')!r} != {declared!r}")
    assert not disagreeing, f"one run, several licences: {disagreeing}"


def test_the_run_declares_a_derived_identity(produced_run: ProducedRun) -> None:
    """Licence, creator, extent, CRS and duration come from the run, not from a literal."""
    attrs = dict(zarr.open_group(str(produced_run.field_store), mode="r").attrs)
    manifest = json.loads(produced_run.manifest.read_text(encoding="utf-8"))
    lies: list[str] = []

    # D1/D5: the licence is derived, from the workspace when it declares one
    # and from nothing otherwise. A literal that happens to change stays wrong.
    declared = _workspace_license(produced_run.workspace)
    expected = {declared} if declared else {"LicenseRef-undetermined"}
    if attrs.get("license") not in expected:
        lies.append(f"license is {attrs.get('license')!r}, expected one of {sorted(expected)}")

    # C1: the declared creator is whoever happened to run the process.
    accounts = _unix_account_names()
    for key in ("creator_name", "publisher_name"):
        if attrs.get(key) in accounts:
            lies.append(f"{key} is the Unix account name {attrs.get(key)!r}")

    # B1: a steady run has no simulated period, so it declares none.
    started = manifest["run"]["started_at"]
    for key in ("time_coverage_start", "time_coverage_end"):
        value = attrs.get(key)
        if value and str(value)[:16] == str(started)[:16]:
            lies.append(f"{key} is the moment of execution")

    # B4: crs_wkt holds a WKT string, or nothing at all.
    crs_wkt = manifest["geometry"].get("crs_wkt")
    if crs_wkt is not None and not str(crs_wkt).startswith(_WKT_PREFIXES):
        lies.append(f"crs_wkt is not WKT: {str(crs_wkt)[:40]!r}")
    if crs_wkt is None and manifest["geometry"]["catchment"].get("crs_proj"):
        lies.append("a CRS is declared in the catchment but crs_wkt is null")

    # B5: the recorded duration is the one the timestamps describe.
    ended_at = datetime.fromisoformat(manifest["run"]["ended_at"])
    started_at = datetime.fromisoformat(manifest["run"]["started_at"])
    elapsed = (ended_at - started_at).total_seconds()
    duration = float(manifest["run"]["duration_s"])
    if not math.isclose(duration, elapsed, rel_tol=0.05, abs_tol=0.05):
        lies.append(f"duration_s is {duration:.3f} s while the timestamps span {elapsed:.3f} s")

    # The store and the seal disagree on the size of the mesh they describe.
    if int(attrs.get("n_cells", 0)) != int(manifest["geometry"]["n_cells"]):
        lies.append(
            f"root n_cells is {attrs.get('n_cells')} while the seal says "
            f"{manifest['geometry']['n_cells']}"
        )

    assert not lies, "declarations that are not derived: " + "; ".join(lies)
