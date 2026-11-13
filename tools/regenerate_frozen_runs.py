"""Write the frozen runs that ``tests/regression/frozen_runs/`` reads at each commit.

Regenerate with one command, once the stored formats have moved on purpose::

    python -m tools.regenerate_frozen_runs

It runs the scaffolded demo and one small calibration with MODFLOW-NWT in a throwaway
workspace, through the same ``hmp`` a user runs, and writes under ``v2.0.0/``:

- ``current/``, the workspace as 2.0.0 stored it;
- ``future/``, the same files as a later 2.x could have written them: an extra key in
  the JSON documents, an extra column in the Parquet tables, an extra array in the Zarr
  stores, and no change of version;
- ``expected.json``, the values the test compares with, read from the raw files by
  ``zarr``, ``pyarrow`` and ``json`` and never by the readers it checks, with one digest
  per copy.

The input, the grid of the search and the numbers come out the same at every run on one
binary. The ids, the timestamps, the durations and the package list of a run do not, so a
second run changes the bytes and not the values. The host, the user and the local paths
never reach the files. The logs stay out, because a run log holds local paths and a pulse
is a transient document.

Nothing runs this at test time: the test only reads what this wrote. After a change of a
stored format, run it, read the diff of ``expected.json`` and commit the three.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import zarr

import hydromodpy as hmp
from hydromodpy.results.storage.parquet_io import write_table_atomic

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests" / "regression" / "frozen_runs" / "v2.0.0"
PROJECT = Path("projects") / "example"
CURRENT = "current"
FUTURE = "future"

FUTURE_KEY = "from_a_later_version"
"""Name of the extra key, column and array of the future copy."""

FUTURE_VALUE = {"kept": True, "note": "written by a later 2.x"}

RUN_ENV = {
    "PYTHONHASHSEED": "42",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}

# Kept small for the frozen copy: one figure at a low resolution and one small export.
FROZEN_RUN_KEYS = "export__delete = true\n\n"
FROZEN_RUN_TABLES = """
[[export]]
variables = "discharge"

[display]
dpi = 40

[[display.figure]]
preset = "water_budget"
"""

CALIBRATION_TOML = """\
base_config = "run_demo.toml"
export__delete = true

[workflow]
mode = "calibration"

[simulation]
name = "calage"
description = "K on three values, scored on one head of the demo."

[calibration]
save_runs = "best_n"
use_cache = false

[calibration.parameters.K]
bounds = [5e-5, 2e-4]
search_space = "log"

[calibration.outputs.upland_head]
support = "point"
variable = "head"
x = 25.0
y = 525.0
observed_values = [20.91]

[[calibration.objective_blocks]]
name = "heads"
metric = "rmse"
uses_outputs = ["upland_head"]

[[calibration.phases]]
name = "k_grid"
parameters = ["K"]
regime = "steady"
objective_blocks = ["heads"]
method = "grid"
max_trials = 3
method_options = { points_per_dim = 3 }

[display]
enabled = false
"""

# Where each stored document takes the extra key. A path is a dotted walk from the root,
# ``*`` standing for every item of a list or every value of a table of named items.
# A free table (the code fingerprints, the catchment facts) is left out: a key there is a
# value, not a key of the document.
FUTURE_KEYS_OF_A_LEDGER = ("", "entries.*", "entries.*.identity", "entries.*.identity.period")
FUTURE_KEYS_OF_A_SESSION = ("", "cases.*", "bounds.*", "windows.*", "best", "best.cases.*")
FUTURE_KEYS: Mapping[str, tuple[str, ...]] = {
    "manifest.json": (
        "",
        "run",
        "geometry",
        "period",
        "config",
        "lineage",
        "identity",
        "identity.period",
        "checks",
        "artifacts.*",
        "parameters.*",
        "metrics.*",
        "score",
        "budget",
    ),
    "provenance.json": ("", "tool", "python", "platform", "solver", "timing", "environment"),
    "inputs.json": ("",),
    "outcome.json": ("",),
    "annotations.json": ("",),
    "index.json": FUTURE_KEYS_OF_A_LEDGER,
    "session.json": FUTURE_KEYS_OF_A_SESSION,
    "products.json": ("", "products.*"),
    "profile.json": ("", "lines.*"),
    "mesh.json": ("",),
}
FUTURE_KEYS_OF_A_META = ("", "identity", "identity.period")
FUTURE_KEYS_OF_A_TRIAL = ("", "params.*", "cases.*")

MACHINE_KEYS = {"hostname", "user", "host"}
"""Keys of a run document that name the machine that wrote it."""

PATH_KEYS = {"binary_path", "path"}
"""Keys of a run document that hold the path of a solver: the file name is enough."""


def main() -> None:
    """Solve, write both copies and the expected values, and print their size."""
    with tempfile.TemporaryDirectory(prefix="hmp-frozen-runs-") as scratch:
        workspace = Path(scratch) / "workspace"
        _solve_the_demo_and_its_calibration(workspace)
        for name in (CURRENT, FUTURE):
            shutil.rmtree(TARGET / name, ignore_errors=True)
        _copy_what_a_reader_needs(workspace, TARGET / CURRENT)
    shutil.copytree(TARGET / CURRENT, TARGET / FUTURE)
    _write_the_future_copy(TARGET / FUTURE)

    expected = _expected_values(TARGET / CURRENT / PROJECT)
    expected["digests"] = {name: _tree_digest(TARGET / name) for name in (CURRENT, FUTURE)}
    (TARGET / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    for name in (CURRENT, FUTURE):
        size = sum(path.stat().st_size for path in (TARGET / name).rglob("*") if path.is_file())
        print(f"{TARGET / name}: {size / 1000:.0f} kB")


def _hmp(*args: str, cwd: Path | None = None) -> None:
    """Run ``hmp`` in its own process, as a user does, with the threads pinned."""
    subprocess.run(
        [sys.executable, "-m", "hydromodpy", *args],
        check=True,
        cwd=cwd,
        env={**os.environ, **RUN_ENV},
    )


def _solve_the_demo_and_its_calibration(workspace: Path) -> None:
    """Scaffold the workspace, then run the demo and the calibration of its K."""
    _hmp("workspace", "init", str(workspace))
    project = workspace / PROJECT
    run_toml = project / "run_demo.toml"
    run_toml.write_text(_with_frozen_run_options(run_toml.read_text(encoding="utf-8")), "utf-8")
    (project / "calage.toml").write_text(CALIBRATION_TOML, encoding="utf-8")

    _hmp("run", str(run_toml), "-w", str(project), cwd=project)
    _hmp("run", str(project / "calage.toml"), "-w", str(project), cwd=project)
    _annotate(project / "runs" / "demo")


def _with_frozen_run_options(text: str) -> str:
    """Return the run TOML with the options of the frozen copy, the top level key first."""
    return text.replace("[workflow]", f"{FROZEN_RUN_KEYS}[workflow]", 1) + FROZEN_RUN_TABLES


def _annotate(run_dir: Path) -> None:
    """Tag the demo and note it, so the frozen tree holds an ``annotations.json``."""
    run = hmp.open(run_dir)
    run.tag("frozen")
    run.note("Frozen for the compatibility test.")


def _copy_what_a_reader_needs(workspace: Path, target: Path) -> None:
    """Copy the project and the workspace file, without what names the machine."""
    project = target / PROJECT
    shutil.copytree(
        workspace / PROJECT, project, ignore=shutil.ignore_patterns(".hmp", ".gitignore", "logs")
    )
    shutil.copy(workspace / "workspace.toml", target / "workspace.toml")
    for name in ("provenance.json", "outcome.json"):
        for path in project.rglob(name):
            payload = json.loads(path.read_text(encoding="utf-8"))
            _write_json(path, _without_the_machine(payload, workspace))
    _neutral_created_at(target / "workspace.toml")
    _refresh_the_sizes_in_the_manifests(project)


def _neutral_created_at(workspace_toml: Path) -> None:
    """The date of the scaffold says nothing about the formats, and a diff need not show it."""
    lines = workspace_toml.read_text(encoding="utf-8").splitlines()
    lines = [
        'created_at = "2000-01-01T00:00:00+00:00"' if ln.startswith("created_at") else ln
        for ln in lines
    ]
    workspace_toml.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _without_the_machine(value: Any, workspace: Path) -> Any:
    """Return *value* with the host, the user and the local paths replaced."""
    if isinstance(value, Mapping):
        return {key: _neutral_item(key, item, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_the_machine(item, workspace) for item in value]
    if isinstance(value, str):
        return value.replace(str(workspace), "<workspace>").replace(str(Path.home()), "~")
    return value


def _neutral_item(key: str, item: Any, workspace: Path) -> Any:
    if key in MACHINE_KEYS:
        return "frozen"
    if key in PATH_KEYS and isinstance(item, str):
        return Path(item).name
    return _without_the_machine(item, workspace)


def _refresh_the_sizes_in_the_manifests(project: Path) -> None:
    """Write in each manifest the size of each artifact as it now stands."""
    for manifest_path in project.rglob("manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for artifact in manifest["artifacts"]:
            if artifact["bytes"] is not None:
                artifact["bytes"] = _size_of(manifest_path.parent / artifact["path"])
        _write_json(manifest_path, manifest)


def _size_of(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- future copy


def _write_the_future_copy(workspace: Path) -> None:
    """Add to each stored file of a copy what a later 2.x could add without a new version."""
    project = workspace / PROJECT
    for path in sorted(project.rglob("*.json")):
        if path.name != "zarr.json":  # the metadata of a Zarr store is not a run document
            _add_keys_to_a_document(path)
    for path in sorted(project.rglob("trials.jsonl")):
        _add_keys_to_a_journal(path)
    for path in sorted(project.glob("**/tables.parquet/*.parquet")):
        _add_a_column(path)
    for path in sorted(project.rglob("fields.zarr")):
        _add_arrays(path)
    _refresh_the_sizes_in_the_manifests(project)


def _add_keys_to_a_document(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.name.endswith(".meta.json"):
        where = FUTURE_KEYS_OF_A_META
    else:
        where = FUTURE_KEYS.get(path.name, ("",))  # a document without a row gets a root key
    for dotted in where:
        for node in _nodes_at(payload, dotted):
            node[FUTURE_KEY] = dict(FUTURE_VALUE)
    _write_json(path, payload)


def _add_keys_to_a_journal(path: Path) -> None:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        for dotted in FUTURE_KEYS_OF_A_TRIAL:
            for node in _nodes_at(payload, dotted):
                node[FUTURE_KEY] = dict(FUTURE_VALUE)
        lines.append(json.dumps(payload, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _nodes_at(payload: Any, dotted: str) -> Iterator[dict[str, Any]]:
    """Yield the tables a dotted path reaches; a path with no table behind it yields nothing."""
    if payload is None:
        return
    if not dotted:
        yield payload
        return
    head, _, rest = dotted.partition(".")
    if head != "*":
        yield from _nodes_at(payload.get(head), rest)
        return
    items = payload if isinstance(payload, list) else payload.values()
    for item in items:
        yield from _nodes_at(item, rest)


def _add_a_column(path: Path) -> None:
    """Add a float column, with the footer of the table and the writer of the code."""
    table = pq.read_table(path)
    values = pa.array(np.arange(table.num_rows, dtype="float64"))
    grown = table.append_column(FUTURE_KEY, values)
    write_table_atomic(grown.replace_schema_metadata(table.schema.metadata), path)


def _add_arrays(store: Path) -> None:
    """Add a field beside ``head``, a budget term, and an attribute on the root."""
    root = zarr.open_group(str(store), mode="r+", use_consolidated=False)
    head = root["head"]
    for parent, name in ((root, FUTURE_KEY), (root["budget"], FUTURE_KEY)):
        array = parent.create_array(
            name=name,
            shape=head.shape,
            chunks=head.chunks,
            dtype="float32",
            dimension_names=head.metadata.dimension_names,
        )
        array[...] = np.full(head.shape, 7.0, dtype="float32")
        array.attrs["units"] = "m"
    root.attrs[FUTURE_KEY] = dict(FUTURE_VALUE)
    zarr.consolidate_metadata(str(store))


# ------------------------------------------------------------------------ expected values


def _expected_values(project: Path) -> dict[str, Any]:
    """Read the values a reader must give from the raw files, without the readers."""
    session_dir = project / "sessions" / "calage"
    return {
        "demo": _expected_of_a_run(project / "runs" / "demo"),
        "calibrated_run": _expected_of_a_run(project / "runs" / "calage"),
        "session": _expected_of_a_session(session_dir),
    }


def _expected_of_a_run(run_dir: Path) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    root = zarr.open_group(str(run_dir / "fields.zarr"), mode="r", use_consolidated=False)
    head = np.asarray(root["head"][...], dtype="float64")
    top = np.asarray(root["mesh"]["topography"][...], dtype="float64")
    tables = run_dir / "tables.parquet"
    annotations = run_dir / "annotations.json"
    exports = run_dir / "exports" / "index.json"
    figures = run_dir / "figures" / "index.json"
    return {
        "sim_id": manifest["run"]["sim_id"],
        "name": manifest["run"]["name"],
        "project": manifest["run"]["project"],
        "solver": manifest["run"]["solver"],
        "flow_regime": manifest["run"]["flow_regime"],
        "status": manifest["run"]["status"],
        "n_cells": manifest["geometry"]["n_cells"],
        "n_layers": manifest["geometry"]["n_layers"],
        "n_timesteps": manifest["period"]["n_timesteps"],
        "period": manifest["period"],
        "budget_pct": manifest["checks"]["budget_pct"],
        "parameters": {row["name"]: row["value"] for row in manifest["parameters"]},
        "lineage": manifest["lineage"],
        "head": _digest_of(head),
        "topography": _digest_of(top),
        "time": np.asarray(root["time"][...]).tolist(),
        "budget_terms": sorted(root["budget"].array_keys()),
        "budget": _rows(tables / "budgets.parquet", "component", "flux_in", "flux_out", "unit"),
        "mass_balance": _rows(
            tables / "mass_balance.parquet", "quantity", "total_in", "total_out", "percent_error"
        ),
        "parameters_table": _rows(tables / "parameters.parquet", "param_name", "value", "unit"),
        "metrics": _rows(tables / "metrics.parquet", "station_id", "variable", "metric", "value"),
        "timeseries": _rows(
            tables / "timeseries.parquet", "station_id", "variable", "source", "value", "unit"
        ),
        "tables": sorted(path.stem for path in tables.glob("*.parquet")),
        "watershed_area_m2": float(
            gpd.read_parquet(tables / "geographic_watershed.parquet").area.sum()
        ),
        "tags": _read_or(annotations, lambda doc: doc["tags"], []),
        "notes": _read_or(annotations, lambda doc: [note["note"] for note in doc["notes"]], []),
        "exports": _read_or(exports, _files_of_a_ledger, []),
        "figures": _read_or(figures, _files_of_a_ledger, []),
    }


def _digest_of(field: np.ndarray) -> dict[str, Any]:
    """Say a field in a few numbers: the shape, the range, one row, and a digest of the values."""
    flat = field.ravel()
    return {
        "shape": list(field.shape),
        "min": float(np.nanmin(flat)),
        "max": float(np.nanmax(flat)),
        "sample": [float(value) for value in flat[:: max(1, flat.size // 19)]],
        "sha256": hashlib.sha256(flat.astype("<f8").tobytes()).hexdigest(),
    }


def _rows(path: Path, *columns: str) -> list[dict[str, Any]]:
    """Read some columns of a table, sorted, so an order of rows is no value."""
    rows = pq.read_table(path, columns=list(columns)).to_pylist()
    return sorted(rows, key=lambda row: [str(row[name]) for name in columns])


def _read_or(path: Path, take: Callable[[dict], Any], default: Any) -> Any:
    if not path.is_file():
        return default
    return take(json.loads(path.read_text(encoding="utf-8")))


def _files_of_a_ledger(ledger: Mapping[str, Any]) -> list[str]:
    return sorted(entry["file"] for entry in ledger["entries"])


def _expected_of_a_session(session_dir: Path) -> dict[str, Any]:
    descriptor = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    # A later line of a trial replaces the earlier one: a promotion names the run it wrote.
    trials = {
        line["trial"]: line
        for line in map(
            json.loads, (session_dir / "trials.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    phases = sorted(path.parent.name for path in session_dir.glob("phases/*/session.json"))
    return {
        "session_id": descriptor["session_id"],
        "case_id": descriptor["case_id"],
        "status": descriptor["status"],
        "method": descriptor["method"],
        "cost_name": descriptor["cost_name"],
        "best": descriptor["best"],
        "windows": descriptor["windows"],
        "bounds": descriptor["bounds"],
        "stop_state": descriptor["stop_state"],
        "phases": phases,
        "trials": [
            {
                "trial": line["trial"],
                "K": line["params"]["K"]["value"],
                "cost": line["cost"],
                "status": line["status"],
                "phase": line["phase"],
                "sim_id": line["cases"]["calage"]["sim_id"],
            }
            for line in trials.values()
        ],
    }


def _tree_digest(tree: Path) -> str:
    """Return the digest of the relative paths and the bytes of every file of a tree."""
    digest = hashlib.sha256()
    for path in sorted(item for item in tree.rglob("*") if item.is_file()):
        digest.update(path.relative_to(tree).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


if __name__ == "__main__":
    main()
