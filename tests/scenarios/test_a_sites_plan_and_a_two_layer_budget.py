"""A plan of sites is written, played and read, and a two-layer budget is split per element.

Two sets on the island of ``factory.py``, played by MODFLOW 6 with two layers. A period has one
solver step, the default, so a budget row and a per-cell field mean the same step, and the run
keeps its per-cell budget, the default of a result run.

1. One run. The outflow of ``budget_over(run, "drain", box, split=True)`` equals ``flux_out`` of
   the ``domain`` row of ``run.budget("drain")`` at each step, within ``2**-17``. The inflow and
   the outflow of ``budget_over(run, "storage", box, split=True)`` equal the sums of the
   ``storage_ss`` and ``storage_sy`` rows. This holds the per-element convention against the
   extractor on a real multilayer run. The ``discharge`` of the ``catchment`` station equals the
   drain outflow over the active domain, and ``run.field("storage_change")`` is refused. The test
   prints the gap between the old convention, which summed the layers of a cell before the sign,
   and the per-element one, for the storage of this run.
2. A ``[sites]`` project of the same island, two sites in ``sites.csv`` whose column ``k`` fills
   the conductivity, one recipe. ``hmp project plan .`` writes ``plan/<hash>/`` with
   ``plan.json`` (``hydromodpy.plan.v2``), a ``cases.csv`` of two rows (the five fixed columns,
   then ``k``) and two TOML files. ``hmp run plan/<hash>/<first case>.toml`` plays one case, and
   ``hmp ls --plan`` says one case completed and one planned. A ``plan.json`` written
   back as ``hydromodpy.plan.v1`` under another hash, named by ``plan/current``, makes
   ``hmp ls --plan`` name ``hmp project plan``.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.core.budget.flux import inflow_outflow
from hydromodpy.core.budget.terms import TERM_FAMILIES
from hydromodpy.results.derive import views
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.plan_store import CASE_COLUMNS, PLAN_SCHEMA
from hydromodpy.results.run.view import open_run_dir
from hydromodpy.results.storage.contract import PLAN_CASES_FILENAME, PLAN_FILENAME
from tests.scenarios.factory import transient_island, write_project
from tests.scenarios.launcher import link_binaries

MF6_FILES = ("mf6", "libmf6.so")
RTOL = 2.0**-17
# Larger than the island, so every face lies whole inside it.
EVERYWHERE = box(-1.0e7, -1.0e7, 1.0e7, 1.0e7)

SITES_TAIL = """
[sites]
table = "sites.csv"

[sites.recipes]
base = "project.toml"

[sites.bind]
"site.name" = "site"
"flow.param.K.field.value" = "k"
"""

SITES_TABLE = "site,k\nwest,5e-6 m/s\neast,1e-5 m/s\n"


def _hmp(root: Path, env: dict[str, str], *argv: str) -> subprocess.CompletedProcess[str]:
    """Run ``python -m hydromodpy`` in *root* with the environment of the scenario."""
    return subprocess.run(
        [sys.executable, "-m", "hydromodpy", *argv],
        cwd=root,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=600,
    )


def _said(result: subprocess.CompletedProcess[str]) -> str:
    """The tail of the command output, the part a failure prints."""
    return (result.stdout[-1500:] + "\n" + result.stderr[-3000:]).strip()


def _two_layers(text: str) -> str:
    """The island text with two layers."""
    assert text.count("nlay = 1\n") == 1
    return text.replace("nlay = 1\n", "nlay = 2\n")


def _sites_project(text: str) -> str:
    """The island text as the root of a ``[sites]`` project: the site and the name are bound."""
    for line in ('[site]\nname = "island"\n\n', 'name = "island"\n'):
        assert text.count(line) == 1
        text = text.replace(line, "", 1)
    return text + SITES_TAIL


def _rows(run, component: str) -> np.ndarray:
    """The ``flux_in`` and ``flux_out`` of the ``domain`` rows of one component, per step."""
    rows = run.budget(component, zone_id="domain").sort_values("timestep")
    return rows[["flux_in", "flux_out"]].to_numpy(dtype="float64")


def _layers_summed_first(run, terms: tuple[str, ...]) -> np.ndarray:
    """Inflow and outflow per step when the layers of a cell are summed before the sign."""
    out = np.zeros((run.n_timesteps, 2))
    for step in range(run.n_timesteps):
        stack = sum(np.asarray(run.field(term, time=step), dtype="float64") for term in terms)
        stack = np.where(np.isfinite(stack) & (stack > -9000.0), stack, 0.0)
        per_cell = stack.reshape(stack.shape[0], -1).sum(axis=0) if stack.ndim > 1 else stack
        out[step] = per_cell.clip(min=0.0).sum(), (-per_cell).clip(min=0.0).sum()
    return out


def test_a_two_layer_budget_is_split_per_element(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    link_binaries(scenario_cache, MF6_FILES)
    root = write_project(
        tmp_path / "island", {"island.toml": _two_layers(transient_island("island", "modflow6"))}
    )
    ran = _hmp(root, scenario_env, "run", "island.toml")
    assert ran.returncode == 0, _said(ran)
    run = open_run_dir(root / "runs" / "island")

    drain = views.budget_over(run, "drain", EVERYWHERE, split=True)
    np.testing.assert_allclose(drain["outflow"], _rows(run, "drain")[:, 1], rtol=RTOL)

    members = [term for term in TERM_FAMILIES["storage"] if term in set(run.budget()["component"])]
    assert members == ["storage_ss", "storage_sy"]
    rows = sum(_rows(run, term) for term in members)
    storage = views.budget_over(run, "storage", EVERYWHERE, split=True)
    np.testing.assert_allclose(storage["inflow"], rows[:, 0], rtol=RTOL, atol=1e-12)
    np.testing.assert_allclose(storage["outflow"], rows[:, 1], rtol=RTOL, atol=1e-12)

    discharge = run.timeseries("discharge", station="catchment").to_numpy(dtype="float64")
    np.testing.assert_allclose(discharge, drain["outflow"].to_numpy(), rtol=RTOL)

    with pytest.raises(FieldNotFoundError, match="storage_change"):
        run.field("storage_change")

    # The old convention against the per-element one, on the storage of this run.
    old = _layers_summed_first(run, tuple(members))
    new = np.zeros_like(old)
    for step in range(run.n_timesteps):
        stack = sum(np.asarray(run.field(term, time=step), dtype="float64") for term in members)
        inflow, outflow = inflow_outflow(stack[np.newaxis])
        new[step] = inflow[0], outflow[0]
    np.testing.assert_allclose(new[:, 0] - new[:, 1], old[:, 0] - old[:, 1], rtol=1e-9, atol=1e-12)
    gap = np.abs(new - old)
    print(f"storage, layers summed first against per element: max gap {gap.max():.6e} m3/s")
    print(f"storage inflow per element {new[:, 0].tolist()}, layers summed {old[:, 0].tolist()}")


def test_a_sites_plan_is_written_played_and_read(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    link_binaries(scenario_cache, MF6_FILES)
    root = write_project(
        tmp_path / "campaign",
        {
            "project.toml": _sites_project(_two_layers(transient_island("island", "modflow6"))),
            "sites.csv": SITES_TABLE,
        },
    )

    planned = _hmp(root, scenario_env, "project", "plan", ".")
    assert planned.returncode == 0, _said(planned)
    plan_hash = (root / "plan" / "current").read_text(encoding="utf-8").strip()
    directory = root / "plan" / plan_hash
    document = json.loads((directory / PLAN_FILENAME).read_text(encoding="utf-8"))
    assert document["schema"] == PLAN_SCHEMA == "hydromodpy.plan.v2"
    with (directory / PLAN_CASES_FILENAME).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        cases = list(reader)
        header = tuple(reader.fieldnames or ())
    assert header == (*CASE_COLUMNS, "k")
    assert [case["site"] for case in cases] == ["west", "east"]
    assert [case["k"] for case in cases] == ["5e-6 m/s", "1e-5 m/s"]
    assert sorted(path.name for path in directory.glob("*.toml")) == sorted(
        case["config_path"] for case in cases
    )

    first = cases[0]
    ran = _hmp(root, scenario_env, "run", f"plan/{plan_hash}/{first['config_path']}")
    assert ran.returncode == 0, _said(ran)
    status = _hmp(root, scenario_env, "ls", "--plan", "--format", "json")
    assert status.returncode == 0, _said(status)
    states = {
        case["case_id"]: case["status"] for case in json.loads(status.stdout)["data"]["cases"]
    }
    assert states == {first["case_id"]: "completed", cases[1]["case_id"]: "planned"}

    # A plan of 2.0 under another hash, named by plan/current, is refused with the command.
    old = root / "plan" / "0000old0"
    shutil.copytree(directory, old)
    document["schema"] = "hydromodpy.plan.v1"
    (old / PLAN_FILENAME).write_text(json.dumps(document), encoding="utf-8")
    (root / "plan" / "current").write_text("0000old0\n", encoding="utf-8")
    refused = _hmp(root, scenario_env, "ls", "--plan")
    assert refused.returncode != 0
    assert "hmp project plan" in refused.stdout + refused.stderr
