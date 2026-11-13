"""A copy is published whole, a replay without values is kept out, and the index is shared.

One project folder, the island of ``factory.py`` played by MODFLOW 6.
Three steps:

1. ``hmp run island.toml`` then ``hmp publish island --to copy``: the copy holds
   the results, ``final_state/``, the inputs with ``INSTALL.toml``,
   ``products.json``, a ``.zenodo.json`` with a title and a version, and an
   RO-Crate that lists it. ``hmp publish --verify`` finds nothing, and the last
   line of ``published.jsonl`` is a copy.
2. ``hmp publish island --to light --without results`` then ``hmp replay light``:
   the seal of the island holds the digest of each value, so the replay is
   compared on the ``float64`` basis, classed bit and published. A copy without
   results of the ``demo`` run of a pre-release, whose seal holds no value digest,
   replays with no class: ``hmp publish`` of that replay is refused with the
   sentence that says why, and ``hmp publish .`` publishes the rest and names
   the replay in ``left_out``.
3. An empty ``index.duckdb.lock`` of yesterday lies in ``.hmp/``, the project
   is held open, and two spawned processes each touch the annotations of a
   different run and index the project at once: both end in time, the index is
   current, no lock is left, the index has blocks of 16 KiB, and the open
   project still reads.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import duckdb

import hydromodpy as hmp
from hydromodpy.cli.exit_codes import exit_code_for
from hydromodpy.core.exceptions import ExportError
from hydromodpy.results.annotations import read_annotations, write_annotations
from hydromodpy.results.catalog.indexer import index_is_current, index_new_runs
from hydromodpy.results.record.manifest import read_seal
from tests.scenarios.factory import transient_island, write_project
from tests.scenarios.launcher import link_binaries

FROZEN = Path(__file__).resolve().parents[1] / "regression" / "frozen_runs" / "v2.0.0" / "current"
SOLVERS = ("mf6", "libmf6.so", "mfnwt", "mfnwtdbl")
BLOCK_SIZE = 16 * 1024


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
    return result.stderr[-3000:]


def _runs_besides(root: Path, known: set[Path]) -> list[Path]:
    """Return the sealed runs of *root* that are not in *known*."""
    return [
        path
        for path in sorted((root / "runs").iterdir())
        if path not in known and (path / "manifest.json").is_file()
    ]


def _touch_and_index(root: str, run_dir: str) -> None:
    """Rewrite the annotations of one run, then index the project; run in a spawned process."""
    write_annotations(run_dir, read_annotations(run_dir))
    index_new_runs(Path(root))


def test_a_copy_is_published_and_the_index_is_shared(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    link_binaries(scenario_cache, SOLVERS)
    root = write_project(
        tmp_path / "project", {"island.toml": transient_island("island", "modflow6")}
    )

    # 1. A copy carries its results and its inputs, its Zenodo metadata, and verifies.
    ran = _hmp(root, scenario_env, "run", "island.toml")
    assert ran.returncode == 0, _said(ran)
    source = root / "runs" / "island"
    copy = tmp_path / "copy"
    published = _hmp(root, scenario_env, "publish", "island", "--to", str(copy))
    assert published.returncode == 0, _said(published)
    names = {entry.name for entry in copy.iterdir()}
    expected = {
        "fields.zarr",
        "tables.parquet",
        "final_state",
        "inputs",
        "INSTALL.toml",
        "products.json",
        ".zenodo.json",
        "ro-crate-metadata.json",
        "PUBLICATION.json",
    }
    assert expected <= names, sorted(names)
    assert ("mesh" in names) is (source / "mesh").is_dir()
    assert not {"request.json", "profile.json", "outcome.json", "logs"} & names
    seal = read_seal(source)
    zenodo = json.loads((copy / ".zenodo.json").read_text(encoding="utf-8"))
    assert zenodo["title"] == seal.run.name
    assert zenodo["version"] == str(seal.run.version)
    crate = json.loads((copy / "ro-crate-metadata.json").read_text(encoding="utf-8"))
    assert ".zenodo.json" in {node.get("@id") for node in crate["@graph"]}
    verified = _hmp(root, scenario_env, "publish", "--verify", str(copy))
    assert verified.returncode == 0, _said(verified)
    journal = (source / "published.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(journal[-1])["kind"] == "copy"

    # 2. A replay of a copy without results of the island is still compared with its seal,
    # whose value digests it reads, so it is classed bit and published.
    light = tmp_path / "light"
    without = _hmp(
        root, scenario_env, "publish", "island", "--to", str(light), "--without", "results"
    )
    assert without.returncode == 0, _said(without)
    assert not (light / "fields.zarr").exists()
    replayed = _hmp(root, scenario_env, "replay", str(light), "-w", str(root))
    assert replayed.returncode == 0, _said(replayed)
    (bit_dir,) = _runs_besides(root, {source})
    bit = read_seal(bit_dir).lineage.replay
    assert bit is not None
    assert (bit.source, bit.basis, bit.class_) == ("copy", "float64", "bit")
    accepted = _hmp(root, scenario_env, "publish", bit_dir.name, "--to", str(tmp_path / "bit"))
    assert accepted.returncode == 0, _said(accepted)

    # A copy without results of the demo of a pre-release carries no value to compare: its replay has no
    # class, so it is refused alone and left out of the copy of the project.
    frozen = tmp_path / "frozen"
    shutil.copytree(FROZEN, frozen)
    demo_project = frozen / "projects" / "example"
    # The frozen demo seals its value digests, so the copy drops them as a pre-release seal.
    sealed = demo_project / "runs" / "demo" / "manifest.json"
    manifest = json.loads(sealed.read_text(encoding="utf-8"))
    del manifest["values"]
    sealed.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    demo_light = tmp_path / "demo_light"
    demo_copy = _hmp(
        demo_project,
        scenario_env,
        "publish",
        "demo",
        "--to",
        str(demo_light),
        "--without",
        "results",
    )
    assert demo_copy.returncode == 0, _said(demo_copy)
    classless = _hmp(root, scenario_env, "replay", str(demo_light), "-w", str(root))
    assert classless.returncode == 0, _said(classless)
    (replay_dir,) = _runs_besides(root, {source, bit_dir})
    lineage = read_seal(replay_dir).lineage
    assert lineage.kind == "replay"
    assert lineage.replay is not None
    assert (lineage.replay.source, lineage.replay.basis) == ("copy", "none")
    assert lineage.replay.class_ is None

    refused_to = tmp_path / "x"
    refused = _hmp(root, scenario_env, "publish", replay_dir.name, "--to", str(refused_to))
    assert refused.returncode == exit_code_for(ExportError("refused")), _said(refused)
    assert "replays a copy that carried no values" in refused.stderr
    assert not refused_to.exists()

    project_copy = tmp_path / "proj"
    whole = _hmp(root, scenario_env, "publish", ".", "--to", str(project_copy), "--format", "json")
    assert whole.returncode == 0, _said(whole)
    left_out = json.loads(whole.stdout)["data"]["left_out"]
    assert [entry["rel_dir"] for entry in left_out] == [f"runs/{replay_dir.name}"]
    assert (project_copy / "island").is_dir()
    assert (project_copy / bit_dir.name).is_dir()
    assert not (project_copy / replay_dir.name).exists()

    # 3. Two writers and a reader share the index, past a stale empty lock.
    lock = root / ".hmp" / "index.duckdb.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(b"")
    yesterday = time.time() - 86400
    os.utime(lock, (yesterday, yesterday))
    project = hmp.open(root)
    try:
        before = len(project.runs())
        context = multiprocessing.get_context("spawn")
        workers = [
            context.Process(target=_touch_and_index, args=(str(root), str(run_dir)))
            for run_dir in (source, replay_dir)
        ]
        started = time.monotonic()
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=60)
        elapsed = time.monotonic() - started
        assert [worker.exitcode for worker in workers] == [0, 0]
        assert elapsed < 30, elapsed
        assert index_is_current(root)
        assert not lock.exists()
        assert len(project.runs()) == before
    finally:
        project.close()
    index = root / ".hmp" / "index.duckdb"
    with duckdb.connect(str(index), read_only=True) as connection:
        (block_size,) = connection.execute(
            "SELECT block_size FROM pragma_database_size()"
        ).fetchone()
    assert block_size == BLOCK_SIZE
