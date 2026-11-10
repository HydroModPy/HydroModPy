"""The documents of 2.0.0 that no frozen run holds, read back by the readers of today.

``v2.0.0/current`` holds a published copy and its ``published.jsonl``, two install
indexes, a plan, a lockfile, three sidecars, two data cache databases, the trial series
of a session, a sealed job with its chain report, and a site catalog. ``expected.json``
holds what the raw files say, read without these readers when the tree was written by
``python -m tools.freeze_documents``. The job comes from a capability ``demo`` that the
generator declares. No test writes under ``v2.0.0/``: every test reads a copy.

HydroModPy 2.1 reads two of these forms no more. The lockfile is schema v1 and is
refused with the sentence that names ``hmp data lock``. The data cache database of the
island is refused by the scan of its data folder with the sentence that names
``hmp workspace clean --data-cache``. The database of a launched case, kept under
``jobs/*/caches/``, held a capability that is gone, since a case writes its files and
sidecars into the shared data folder. See ``README.md`` beside it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.core.exceptions import DataCacheError, SchemaVersionMismatchError
from hydromodpy.core.payload.index import read_index
from hydromodpy.data.provenance.lockfile import read_lockfile_inputs
from hydromodpy.data.provenance.sidecars import (
    FORMER_CACHE_DATABASE,
    load_sidecar,
    scan,
)
from hydromodpy.data.sites.catalog import read_catalog
from hydromodpy.results.export.publish import verify
from hydromodpy.results.plan_store import current_plan_hash, read_plan
from hydromodpy.results.publication import read_publication, read_published
from hydromodpy.results.session.trial_series import read_trial_series
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_versioned
from hydromodpy.schema.job.inputset import INPUTSET_VERSIONS
from hydromodpy.schema.job.outcome import OUTCOME_VERSIONS, JobOutcome
from hydromodpy.schema.job.provenance import PROVENANCE_VERSIONS
from hydromodpy.schema.job.request import read_request
from hydromodpy.schema.job.seal import read_job_seal, verify_job
from hydromodpy_annex.schema.job_chain.chain import read_chain_outcome

FROZEN = Path(__file__).parent / "v2.0.0"
EXPECTED: dict[str, Any] = json.loads((FROZEN / "expected.json").read_text(encoding="utf-8"))

SIZE_LIMIT_BYTES = 1_500_000
"""The corpus stays near one MB, most of it the floor size of two DuckDB files."""

TEXT_SUFFIXES = {".json", ".jsonl", ".toml", ".md", ".csv", ".lock"}


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One copy of ``current/`` outside the repository, shared by the tests that read."""
    target = tmp_path_factory.mktemp("frozen_documents") / "current"
    shutil.copytree(FROZEN / "current", target)
    return target


def _tree_digest(tree: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in tree.rglob("*") if item.is_file()):
        digest.update(path.relative_to(tree).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# ---------------------------------------------------------------------- the frozen tree


def test_the_frozen_bytes_have_not_moved() -> None:
    """A test that writes in the tree, or a regeneration without its values, fails here."""
    assert _tree_digest(FROZEN / "current") == EXPECTED["digest"]


def test_the_corpus_stays_small() -> None:
    size = sum(path.stat().st_size for path in (FROZEN / "current").rglob("*") if path.is_file())
    assert size < SIZE_LIMIT_BYTES


def test_the_corpus_names_no_machine() -> None:
    for path in (FROZEN / "current").rglob("*"):
        if path.suffix in TEXT_SUFFIXES:
            assert "/home/" not in path.read_text(encoding="utf-8"), path


# ----------------------------------------------------------------- one test per document


def test_published_lines(corpus: Path) -> None:
    lines = read_published(corpus / "island" / "runs" / "calage")
    assert [
        {"schema": line.schema_, "to": line.to, "format": line.format} for line in lines
    ] == EXPECTED["published"]


def test_publication(corpus: Path) -> None:
    expected = EXPECTED["publication"]
    publication = read_publication(corpus / "publication")
    assert (publication.schema_, publication.kind) == (expected["schema"], expected["kind"])
    assert publication.source.rel_dir == expected["rel_dir"]
    assert sorted(publication.files) == expected["files"]
    assert verify(corpus / "publication") == []


@pytest.mark.parametrize("folder", ["publication", "install"])
def test_install_index(corpus: Path, folder: str) -> None:
    expected = EXPECTED["install"][folder]
    index = read_index(corpus / folder)
    assert index.hydromodpy_version == expected["hydromodpy_version"]
    assert [item.dest for item in index.files] == expected["files"]
    assert [item.id for item in index.stations] == expected["stations"]
    assert [item.site for item in index.sites] == expected["sites"]


def test_plan_and_its_tables(corpus: Path) -> None:
    expected = EXPECTED["plan"]
    project = corpus / "campaign"
    assert current_plan_hash(project) == expected["plan_hash"]
    stored = read_plan(project)
    assert (stored.plan.schema_, stored.plan.plan_hash) == (
        expected["schema"],
        expected["plan_hash"],
    )
    assert (stored.plan.n_cases, stored.plan.budget) == (expected["n_cases"], expected["budget"])
    assert sorted(case.case_id for case in stored.cases) == expected["cases"]
    assert sorted(stored.sites.column("site").to_pylist()) == expected["sites"]
    for case_id in expected["cases"]:
        assert tomllib.loads(stored.case_toml(case_id))["simulation"]["name"] == case_id


def test_lockfile(corpus: Path) -> None:
    """The lockfile of 2.0.0 is schema v1, which 2.1 refuses and tells how to write again."""
    expected = EXPECTED["lockfile"]
    lockfile = corpus / "island" / "hydromodpy.lock"
    assert tomllib.loads(lockfile.read_text(encoding="utf-8"))["schema"] == expected["schema"]
    with pytest.raises(SchemaVersionMismatchError) as caught:
        read_lockfile_inputs(lockfile)
    message = str(caught.value)
    assert expected["schema"] in message
    assert "hydromodpy.lock.v2" in message
    assert "hmp data lock" in message


@pytest.mark.parametrize("sidecar", sorted(EXPECTED["sidecar"]))
def test_sidecar(corpus: Path, sidecar: str) -> None:
    data_file = corpus / sidecar.removesuffix(".json")
    # A field 2.1 added reads as its default, which the raw file does not state.
    read = load_sidecar(data_file).model_dump(mode="json", exclude_defaults=True)
    raw = EXPECTED["sidecar"][sidecar]
    expected = {key: value for key, value in raw.items() if value is not None}
    # 2.1.0 renamed the local source: a sidecar of 2.0.0 that says "custom" reads as "file".
    if expected.get("source") == "custom":
        expected["source"] = "file"
    assert {key: value for key, value in read.items() if value is not None} == expected


ISLAND_CACHE = f"island/data/{FORMER_CACHE_DATABASE}"
"""The one data cache database of the corpus that a data folder holds."""


def test_the_database_of_a_data_folder_is_refused_by_the_scan(corpus: Path) -> None:
    """The scan names the database and the command that removes it, and reads nothing else."""
    assert ISLAND_CACHE in EXPECTED["data_cache"]
    assert (corpus / ISLAND_CACHE).name == FORMER_CACHE_DATABASE
    with pytest.raises(DataCacheError) as caught:
        scan(corpus / "island" / "data")
    message = str(caught.value)
    assert str(corpus / ISLAND_CACHE) in message
    assert "hmp workspace clean --data-cache" in message


def test_the_island_sidecars_sort_into_rows_user_files_and_the_unnamed(
    corpus: Path, tmp_path: Path
) -> None:
    """Once the database is removed, the sidecars of 2.0.0 are read by the rules of 2.1."""
    data = tmp_path / "data"
    shutil.copytree(corpus / "island" / "data", data)
    (data / FORMER_CACHE_DATABASE).unlink()
    report = scan(data)
    assert [(row.variable, row.source, row.station_id) for row in report.rows] == [
        ("piezometry", "hubeau", None)
    ]
    assert [path.name for path in report.user_files] == ["piezometry_custom_W1_D.csv"]
    assert [path.name for path in report.without_variable] == ["dem_ign.tif.json"]
    assert any("without its variable" in line for line in report.lines())


def test_trial_series(corpus: Path) -> None:
    expected = EXPECTED["trial_series"]
    frame = read_trial_series(corpus / "island" / "sessions" / "calage")
    assert list(frame.columns) == expected["columns"]
    rows = frame.to_dict("records")
    for row in rows:
        row["time"] = row["time"].isoformat()
    assert rows == expected["rows"]


def test_sealed_job_and_its_chain(corpus: Path) -> None:
    expected = EXPECTED["job"]
    chain = read_chain_outcome(corpus / "chain")
    assert (chain["schema"], chain["status"]) == (
        expected["chain"]["schema"],
        expected["chain"]["status"],
    )
    job = JobDirectory.for_reading(corpus / "chain" / expected["directory"])
    request = read_request(job)
    assert request.process.id == expected["request"]["process"]["id"] == EXPECTED["capability"]
    assert request.inputs == expected["request"]["inputs"]
    assert read_versioned(job.inputset_path, INPUTSET_VERSIONS)["schema"] == expected["inputset"]
    assert (
        read_versioned(job.provenance_path, PROVENANCE_VERSIONS)["schema"] == expected["provenance"]
    )
    outcome = JobOutcome.from_document(read_versioned(job.outcome_path, OUTCOME_VERSIONS))
    assert (outcome.status, outcome.job_id) == (
        expected["outcome"]["status"],
        expected["outcome"]["job_id"],
    )
    assert [record.path for record in outcome.outputs] == expected["outcome"]["outputs"]
    seal = read_job_seal(job.manifest_path)
    assert (seal.profile, seal.request_id) == ("job", outcome.job_id)
    verification = verify_job(job)
    assert verification.ok, verification.problems


def test_site_catalog(corpus: Path) -> None:
    rows = read_catalog(corpus / "workspace")
    assert [row.site for row in rows] == EXPECTED["sites_catalog"]["sites"]
    assert rows[0].tags == ("a", "b")
