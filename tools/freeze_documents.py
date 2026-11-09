"""Write the documents that ``tests/regression/frozen_documents/`` reads.

Run it from the root of the repository, on the export of the release tag that the
corpus names::

    python -m tools.freeze_documents

``tests/regression/frozen_runs/`` holds a run and a session. This holds the other
documents a release stores: the ``published.jsonl`` of a run, a published copy with its
``PUBLICATION.json`` and ``INSTALL.toml``, an install index with a station row, the plan
of a ``[sites]`` project, a lockfile, three sidecars, the trial series of a session, a
sealed job with its chain report, and a site catalog. Each one comes from its real
writer, on a synthetic island, with no network. The job comes from a capability ``demo``
that this script declares, because no real capability writes a job without a local path
in its request.

The script writes no data cache database. HydroModPy 2.1 keeps the cache in the sidecars
and refuses the database of 2.0.0 by name, so no current code can write one. The two databases of
``v2.0.0/current`` were written by 2.0.0 and stay as they are. For the same reason the
script refuses to write ``v2.0.0/`` from a version other than 2.0, whose lockfile has
another schema: that folder is written again only on the export of the tag.

The script restarts itself in a throwaway HOME, state and cache, with the solver
binaries of the machine linked in. It writes ``<release>/current/`` and
``<release>/expected.json``, or the same under ``--out``. ``expected.json`` holds the
version keys, the counts and the values of each document, read from the raw files by
``json``, ``tomllib`` and ``pyarrow`` and never by the readers the test checks, with the
version of pyarrow that wrote them and one digest of the tree.

The values of ``expected.json`` come out the same at every run on one binary, apart from
the digest and the commit it names. The bytes of some files do not: the ``created_at``
of the plan, the lockfile (``git_commit``, ``python_version``, ``generated_at`` and
``fetched_at``), and the published copy with ``published.jsonl``, which name the run id
and its dates. The chain, the job, the sidecars, the install index, the trial series and
the site catalog come out byte for byte. The one value rewritten after its writer is the
``to`` of each published line, a local path, turned into ``<workspace>/...``.

Nothing runs this at test time: the test only reads what this wrote.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
import pyarrow
import pyarrow.parquet as pq
import rasterio
from pydantic import BaseModel, ConfigDict
from rasterio.transform import from_origin

import hydromodpy.schema.job.outcome as outcome_module
import hydromodpy.schema.job.seal as seal_module
import hydromodpy.schema.job.worker as worker_module
import hydromodpy_annex.schema.job_chain.chain as chain_module
from hydromodpy.core.payload.index import (
    InstallIndex,
    PayloadFile,
    PayloadStation,
    write_index,
)
from hydromodpy.core.site.row import SiteRow
from hydromodpy.core.version import __version__
from hydromodpy.data.provenance.sidecars import Sidecar, compute_sha256, write_sidecar
from hydromodpy.model.domain.job_inputs import output_records
from hydromodpy.schema.capability import CapabilityDecl, OutputDecl
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.inputset import build_inputset, inline_resource
from hydromodpy.schema.job.outcome import JobOutcome
from hydromodpy.schema.job.provenance import build_provenance
from hydromodpy.schema.job.request import content_address, read_request, validate_inputs
from hydromodpy.schema.job.worker import run_job, seal_successful
from hydromodpy.schema.media_types import JSON_MEDIA_TYPE
from hydromodpy_annex.schema.job_chain.chain import ChainRequest, run_chain
from tests.scenarios.factory import island_files, write_project
from tests.scenarios.launcher import isolated_env, link_binaries

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests" / "regression" / "frozen_documents" / "v2.0.0"
CURRENT = "current"
NEEDS = ("mf6", "libmf6.so")

SIZE_LIMIT_BYTES = 1_500_000
FILE_LIMIT_BYTES = 1_000 * 1024
"""The total the test keeps, and the file size ``check-added-large-files`` refuses."""

TEXT_SUFFIXES = {".json", ".jsonl", ".toml", ".md", ".csv", ".txt", ".lock"}

FIXED_INSTANT = "2026-01-01T00:00:00+00:00"
"""The instant of every date the chain and the job write, in the spelling of ``now()``."""

CAPABILITY = "demo"
OUTPUT_PATH = "outputs/value.json"

CAMPAIGN_PROJECT = """\
[workspace]
data_dir = "data"

[workflow]
mode = "simulation"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
dem_init_path = "dem.tif"
snap_dist = "150 m"
buff_area = "10%"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-03-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "steady"
param_list = ["K"]

[flow.param.K.field]
kind = "homogeneous"
unit = "m/s"
value = 5e-5

[flow.bc.drainage]
kind = "drain"

[sites]
table = "sites.csv"

[sites.recipes]
base = "project.toml"
k2e_5 = { file = "project.toml", set = { "flow.param.K.field.value" = 2e-5 } }

[sites.bind]
"site.name" = "site"
"geographic.catchment.x_outlet" = "x_outlet"
"geographic.catchment.y_outlet" = "y_outlet"
"""

CAMPAIGN_SITES = "site,x_outlet,y_outlet\nalpha,389285.9,6816518.7\nbeta,377120.0,6831410.0\n"

HUBEAU_RECORD = "datetime,value\n2003-01-01,2.5\n2003-01-02,2.6\n"


def main(argv: list[str] | None = None) -> None:
    """Restart in a throwaway environment, then copy the corpus and write its values."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=TARGET, help="folder of current/")
    parser.add_argument("--scratch", type=Path, help="work folder, kept (default: a temp one)")
    parser.add_argument("--inside", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.inside is not None:
        _write_documents(args.inside)
        return
    if args.out.resolve() == TARGET and not __version__.startswith("2.0"):
        sys.exit(
            f"{TARGET} holds the documents of 2.0.0 and is written on the export of that tag "
            f"only, not by {__version__}. Pass --out to write another folder."
        )
    with ExitStack() as stack:
        if args.scratch is None:
            scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="hmp-docs-")))
        else:
            scratch = args.scratch.resolve()
            shutil.rmtree(scratch, ignore_errors=True)
        _generate(scratch, args.out.resolve())


def _generate(scratch: Path, out: Path) -> None:
    work = scratch / "work"
    env = isolated_env(scratch / "home", scratch / "cache", scratch / "state", scratch / "tmp")
    link_binaries(scratch / "cache", NEEDS)
    subprocess.run(
        [sys.executable, "-m", "tools.freeze_documents", "--inside", str(work)],
        check=True,
        cwd=ROOT,
        env=env,
    )
    shutil.rmtree(out / CURRENT, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(work / CURRENT, out / CURRENT)
    tree = out / CURRENT
    _refuse_a_machine_path(tree, (str(scratch), str(Path.home()), "/home/", "/Users/"))
    _refuse_a_big_tree(tree)
    expected = _expected_values(tree)
    expected["digest"] = _tree_digest(tree)
    (out / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    size = sum(path.stat().st_size for path in tree.rglob("*") if path.is_file())
    print(f"{tree}: {size / 1000:.0f} kB")


# ------------------------------------------------------------------ inside the throwaway env


def _write_documents(work: Path) -> None:
    """Write every document by its writer under *work*, then gather them in ``current/``."""
    island = _calibrate_lock_and_publish(work)
    _write_sidecars(island / "data")
    _write_install_index(work / "install")
    campaign = _plan_the_campaign(work / "campaign")
    _write_chain(work / "chain")
    workspace = _write_site_catalog(work / "workspace")
    _gather(work, island, campaign, workspace)


def _hmp(*args: str, cwd: Path) -> None:
    """Run ``hmp`` in its own process, as a user does, in the environment of this one."""
    subprocess.run([sys.executable, "-m", "hydromodpy", *args], check=True, cwd=cwd)


def _calibrate_lock_and_publish(work: Path) -> Path:
    """Calibrate the island, lock its inputs, and publish its run twice."""
    island = write_project(work / "island", island_files("calage"))
    _hmp("calibrate", "calib.toml", cwd=island)
    _hmp("data", "lock", "--project", ".", cwd=island)
    _hmp("publish", "calage", "--to", str(work / "pub" / "inputs"), "--with", "inputs", cwd=island)
    tar = str(work / "pub" / "calage.tar")
    _hmp("publish", "calage", "--to", tar, "--container", "tar", cwd=island)
    return island


def _write_sidecars(data: Path) -> None:
    """Write a downloaded chronicle and a raster, each with its sidecar."""
    chronicle = data / "piezometry" / "piezometry_hubeau_W2_D.csv"
    chronicle.write_text(HUBEAU_RECORD, encoding="utf-8")
    write_sidecar(
        chronicle,
        Sidecar(
            source="hubeau",
            sha256=compute_sha256(chronicle),
            bytes=chronicle.stat().st_size,
            license="etalab-2.0",
            variable="piezometry",
            unit="m",
            source_unit="m",
            frequency="D",
            date_start="2003-01-01",
            date_end="2003-01-02",
        ),
    )
    raster = data / "dem" / "dem_ign.tif"
    raster.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "width": 2,
        "height": 2,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:2154",
        "transform": from_origin(0.0, 610.0, 305.0, 305.0),
    }
    with rasterio.open(raster, "w", **profile) as dst:
        dst.write(np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float32"), 1)
    write_sidecar(
        raster,
        Sidecar(
            source="ign",
            sha256=compute_sha256(raster),
            bytes=raster.stat().st_size,
            variable="dem",
            license="etalab-2.0",
            crs="EPSG:2154",
            bbox=(0.0, 0.0, 610.0, 610.0),
            notes="Synthetic terrain of four cells.",
        ),
    )


def _write_install_index(folder: Path) -> None:
    """Write an install index with a file, a station row and a site.

    The island has no station registry row to ship, so its published copy holds
    no ``[[station]]``. This index holds one, through the same writer.
    """
    folder.mkdir(parents=True, exist_ok=True)
    index = InstallIndex(
        files=(
            PayloadFile(
                dest="data/piezometry/piezometry_hubeau_W2_D.csv",
                size=len(HUBEAU_RECORD.encode("utf-8")),
                sha256=hashlib.sha256(HUBEAU_RECORD.encode("utf-8")).hexdigest(),
                root="project",
                variable="piezometry",
                provider="hubeau",
                license="etalab-2.0",
                request={"station": "W2", "period": ["2003-01-01", "2003-01-02"]},
            ),
        ),
        stations=(
            PayloadStation(
                dest="data/piezometry/piezometry_hubeau_LOC.csv",
                row=(("id", "W2"), ("x", "305.0"), ("y", "305.0")),
            ),
        ),
        sites=(SiteRow(site="island", label="Island", gauge="W2"),),
    )
    write_index(folder, index)


def _plan_the_campaign(campaign: Path) -> Path:
    """Plan a two-site, two-recipe project."""
    write_project(
        campaign,
        {"project.toml": CAMPAIGN_PROJECT, "sites.csv": CAMPAIGN_SITES},
    )
    (campaign / "data").mkdir()
    (campaign / "dem.tif").write_bytes(b"never read by the plan")
    _hmp("project", "plan", ".", cwd=campaign)
    return campaign


class DemoInputs(BaseModel):
    """What the ``demo`` capability reads: one integer."""

    model_config = ConfigDict(extra="forbid")

    value: int = 0


DEMO = CapabilityDecl(
    id=CAPABILITY,
    version="1.0.0",
    title="Demo",
    description="Writes back the integer it was given.",
    keywords=("demo",),
    request_model=DemoInputs,
    outputs=(
        OutputDecl(
            id="value",
            title="The value",
            path=OUTPUT_PATH,
            media_type=JSON_MEDIA_TYPE,
            roles=("data",),
        ),
    ),
    exceptions=(ValueError,),
)


@dataclass(frozen=True)
class _Resolved:
    job_id: str
    value: int


def _resolve(job: JobDirectory) -> _Resolved:
    inputs = validate_inputs(read_request(job), DEMO)
    asked = inputs.model_dump()
    job_id = content_address(process_id=DEMO.id, process_version=DEMO.version, inputs=asked)
    return _Resolved(job_id=job_id, value=asked["value"])


def _execute(job: JobDirectory, resolved: _Resolved, started_at: str) -> JobOutcome:
    job.ensure_workspace()
    (job.root / OUTPUT_PATH).write_text(json.dumps({"value": resolved.value}) + "\n", "utf-8")
    resource = inline_resource(
        "value", role="parameter", value=resolved.value, pointer="/inputs/value"
    )
    # The input set stamps its own creation time; it is fixed before the seal hashes it.
    inputset = replace(build_inputset([resource]), created_at=FIXED_INSTANT)
    return seal_successful(
        job,
        decl=DEMO,
        job_id=resolved.job_id,
        inputset=inputset,
        backend=None,
        outputs=lambda: output_records(job, DEMO),
        warnings=(),
        started_at=started_at,
    )


def _run_step(capability: str, directory: Path) -> tuple[int, str]:
    job = JobDirectory.open(directory)
    outcome = run_job(
        job, decl=DEMO, resolve=_resolve, execute=_execute, exit_code_for=lambda exc: 1
    )
    return outcome.exit_code, job.outcome_path.read_text(encoding="utf-8")


def _frozen_provenance(**kwargs: Any) -> dict[str, Any]:
    """Build the provenance, then fix what names the machine, before anything is sealed."""
    document = build_provenance(**kwargs)
    document["git"] = {"commit": "0" * 40, "dirty": False}
    document["python"] = {"version": "frozen", "implementation": "frozen"}
    document["platform"] = {"platform": "frozen", "system": "frozen", "machine": "frozen"}
    document["packages"] = {"hydromodpy": __version__}
    return document


def _write_chain(root: Path) -> None:
    """Run a chain of one ``demo`` step, which seals its job, at a fixed instant."""
    root.mkdir(parents=True, exist_ok=True)
    request = ChainRequest.model_validate(
        {"steps": [{"id": "first", "process": {"id": CAPABILITY}, "inputs": {"value": 1}}]}
    )
    with ExitStack() as stack:
        for module in (chain_module, outcome_module, seal_module, worker_module):
            stack.enter_context(mock.patch.object(module, "now", lambda: FIXED_INSTANT))
        stack.enter_context(
            mock.patch.object(worker_module, "build_provenance", _frozen_provenance)
        )
        result = run_chain(
            request,
            root,
            declaration=lambda capability: DEMO if capability == CAPABILITY else None,
            run_step=_run_step,
            exit_code_for=lambda exc: 1,
        )
    if result.exit_code != 0:
        raise RuntimeError(f"the chain failed: {result.document}")


def _write_site_catalog(workspace: Path) -> Path:
    """Scaffold a workspace and add a full site and a site with its name alone."""
    _hmp("workspace", "init", str(workspace), cwd=workspace.parent)
    _hmp(
        "site", "add", "alpha", "--outlet", "389285.9", "6816518.7", "--label", "Alpha",
        "--gauge", "W1", "--uri", "hubeau:J001", "--tag", "a", "--tag", "b",
        cwd=workspace,
    )  # fmt: skip
    _hmp("site", "add", "beta", cwd=workspace)
    return workspace


def _gather(work: Path, island: Path, campaign: Path, workspace: Path) -> None:
    """Copy what a reader reads into ``current/``, and nothing that names the machine."""
    target = work / CURRENT
    copy = target / "island"
    for name in ("project.toml", "calib.toml", "hydromodpy.lock"):
        _copy_file(island / name, copy / name)
    shutil.copytree(island / "data", copy / "data")
    _copy_published(island / "runs" / "calage", copy / "runs" / "calage", work)
    shutil.copytree(
        island / "sessions" / "calage" / "trial_series",
        copy / "sessions" / "calage" / "trial_series",
    )
    shutil.copytree(work / "pub" / "inputs", target / "publication")
    shutil.copytree(work / "install", target / "install")
    for name in ("project.toml", "sites.csv", "dem.tif"):
        _copy_file(campaign / name, target / "campaign" / name)
    shutil.copytree(campaign / "plan", target / "campaign" / "plan")
    shutil.copytree(work / "chain", target / "chain")
    _copy_file(
        workspace / "data" / "sites" / "catalog.csv",
        target / "workspace" / "data" / "sites" / "catalog.csv",
    )


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_published(run_dir: Path, target: Path, work: Path) -> None:
    """Copy ``published.jsonl`` with each destination written relative to the work folder."""
    target.mkdir(parents=True, exist_ok=True)
    lines = []
    for text in (run_dir / "published.jsonl").read_text(encoding="utf-8").splitlines():
        line = json.loads(text)
        line["to"] = "<workspace>/" + Path(line["to"]).relative_to(work).as_posix()
        lines.append(json.dumps(line, ensure_ascii=False))
    (target / "published.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- checks


def _text_files(tree: Path) -> Iterator[Path]:
    for path in sorted(tree.rglob("*")):
        if path.is_file() and (path.suffix in TEXT_SUFFIXES or path.name == "current"):
            yield path


def _refuse_a_machine_path(tree: Path, needles: tuple[str, ...]) -> None:
    """Fail on any text file that names the work folder, a home or a user folder."""
    found = [
        f"{path.relative_to(tree)}: {needle}"
        for path in _text_files(tree)
        for needle in needles
        if needle in path.read_text(encoding="utf-8")
    ]
    if found:
        raise RuntimeError("the corpus names the machine:\n" + "\n".join(found))


def _refuse_a_big_tree(tree: Path) -> None:
    sizes = {path: path.stat().st_size for path in tree.rglob("*") if path.is_file()}
    big = [
        f"{path.relative_to(tree)}: {size}"
        for path, size in sizes.items()
        if size > FILE_LIMIT_BYTES
    ]
    if big or sum(sizes.values()) > SIZE_LIMIT_BYTES:
        raise RuntimeError(f"the corpus is {sum(sizes.values())} bytes; files too big: {big}")


def _tree_digest(tree: Path) -> str:
    """Return the digest of the relative paths and the bytes of every file of a tree."""
    digest = hashlib.sha256()
    for path in sorted(item for item in tree.rglob("*") if item.is_file()):
        digest.update(path.relative_to(tree).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# ------------------------------------------------------------------------ expected values


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def _expected_values(tree: Path) -> dict[str, Any]:
    """Read the values a reader must give from the raw files, without the readers."""
    return {
        "hydromodpy_version": __version__,
        "written_from": {
            "commit": _git("rev-parse", "HEAD"),
            # Dirty when the package that wrote the corpus differs from that commit.
            "dirty": bool(
                _git("status", "--porcelain", "--untracked-files=no", "--", "hydromodpy")
            ),
        },
        "pyarrow_version": pyarrow.__version__,
        "capability": CAPABILITY,
        "published": _expected_published(tree / "island" / "runs" / "calage" / "published.jsonl"),
        "publication": _expected_publication(tree / "publication" / "PUBLICATION.json"),
        "install": {
            "publication": _expected_install(tree / "publication" / "INSTALL.toml"),
            "install": _expected_install(tree / "install" / "INSTALL.toml"),
        },
        "plan": _expected_plan(tree / "campaign"),
        "lockfile": _expected_lockfile(tree / "island" / "hydromodpy.lock"),
        "sidecar": {
            path.relative_to(tree).as_posix(): _json(path)
            for path in sorted((tree / "island" / "data").rglob("*.json"))
        },
        "trial_series": _expected_trial_series(
            tree / "island" / "sessions" / "calage" / "trial_series"
        ),
        "job": _expected_job(tree / "chain"),
        "sites_catalog": _expected_catalog(tree / "workspace" / "data" / "sites" / "catalog.csv"),
    }


def _expected_published(path: Path) -> list[dict[str, Any]]:
    lines = [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()]
    return [{key: line[key] for key in ("schema", "to", "format")} for line in lines]


def _expected_publication(path: Path) -> dict[str, Any]:
    document = _json(path)
    return {
        "schema": document["schema"],
        "kind": document["kind"],
        "rel_dir": document["source"]["rel_dir"],
        "files": sorted(document["files"]),
    }


def _expected_install(path: Path) -> dict[str, Any]:
    document = _toml(path)
    return {
        "schema": document["schema"],
        "hydromodpy_version": document["hydromodpy_version"],
        "files": [table["dest"] for table in document.get("file", [])],
        "stations": [table["row"]["id"] for table in document.get("station", [])],
        "sites": [table["site"] for table in document.get("site", [])],
    }


def _expected_plan(project: Path) -> dict[str, Any]:
    plan_hash = (project / "plan" / "current").read_text(encoding="utf-8").strip()
    directory = project / "plan" / plan_hash
    plan = _json(directory / "plan.json")
    cases = pq.read_table(directory / "cases.parquet").to_pylist()
    return {
        "schema": plan["schema"],
        "plan_hash": plan_hash,
        "n_cases": plan["n_cases"],
        "budget": plan["budget"],
        "cases": sorted(row["case_id"] for row in cases),
        "case_tomls": sorted(path.name for path in directory.glob("*.toml")),
        "sites": sorted(pq.read_table(directory / "sites.parquet").column("site").to_pylist()),
    }


def _expected_lockfile(path: Path) -> dict[str, Any]:
    document = _toml(path)
    return {
        "schema": document["schema"],
        "inputs": [
            {key: item[key] for key in ("variable", "source", "path", "sha256", "license")}
            for item in document.get("input", [])
        ],
    }


def _expected_trial_series(folder: Path) -> dict[str, Any]:
    rows = []
    for path in sorted(folder.glob("trial-*.parquet")):
        table = pq.read_table(path)
        columns = table.column_names
        for row in table.to_pylist():
            row["time"] = row["time"].isoformat()
            rows.append(row)
    return {
        "files": sorted(path.name for path in folder.glob("*.parquet")),
        "columns": columns,
        "rows": rows,
    }


def _expected_job(root: Path) -> dict[str, Any]:
    chain = _json(root / "chain-outcome.json")
    job = root / chain["steps"][0]["dir"]
    manifest = _json(job / "manifest.json")
    outcome = _json(job / "outcome.json")
    return {
        "chain": {
            "schema": chain["schema"],
            "status": chain["status"],
            "steps": len(chain["steps"]),
        },
        "directory": job.name,
        "request": _json(job / "request.json"),
        "inputset": _json(job / "inputset.json")["schema"],
        "provenance": _json(job / "provenance.json")["schema"],
        "outcome": {
            "schema": outcome["schema"],
            "status": outcome["status"],
            "job_id": outcome["job_id"],
            "outputs": [entry["path"] for entry in outcome["outputs"]],
        },
        "manifest": {
            "schema": manifest["schema"],
            "profile": manifest["profile"],
            "artifacts": sorted(entry["path"] for entry in manifest["artifacts"]),
        },
    }


def _expected_catalog(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return {"header": lines[0].split(","), "sites": [line.split(",")[0] for line in lines[1:]]}


if __name__ == "__main__":
    main()
