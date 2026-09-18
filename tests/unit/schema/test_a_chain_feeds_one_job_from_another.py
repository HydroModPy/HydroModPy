"""Two capabilities compose through the disk, and the chain is what writes it.

The mechanics are checked against declarations built here, because the chain
knows no capability and asserting it against the two this build ships would
hide that. One test does use the real pair, and it is the contract of the
phase: the GeoPackage ``terrain-delineate`` seals fills the ``mask`` member of
``data-fetch``, at the path the declaration gives it and nowhere else.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.exceptions import ConfigValidationError, JobUsageError
from hydromodpy.schema.capability import CapabilityDecl, OutputDecl
from hydromodpy.schema.job.chain import (
    CHAIN_FILENAME,
    CHAIN_OUTCOME_FILENAME,
    ChainOutcome,
    ChainRequest,
    read_chain,
    resolve_chain,
    run_chain,
)
from hydromodpy.schema.job.directory import JobDirectory

PRODUCER_ID = "make-thing"
CONSUMER_ID = "read-thing"
THING_PATH = "outputs/thing.gpkg"
THING_MEDIA_TYPE = "application/geopackage+sqlite3"


class _Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int = 0


def _decl(capability_id: str, *, required: bool = True) -> CapabilityDecl:
    return CapabilityDecl(
        id=capability_id,
        version="1.0.0",
        title=f"capability {capability_id}",
        description=f"what {capability_id} does",
        keywords=("test",),
        request_model=_Inputs,
        outputs=(
            OutputDecl(
                id="thing",
                title="the artefact the next step reads",
                path=THING_PATH,
                media_type=THING_MEDIA_TYPE,
                roles=("data", "primary"),
                required=required,
            ),
        ),
        exceptions=(ValueError,),
    )


DECLS = {PRODUCER_ID: _decl(PRODUCER_ID), CONSUMER_ID: _decl(CONSUMER_ID, required=False)}


def _declaration(capability_id: str) -> CapabilityDecl | None:
    return DECLS.get(capability_id)


def _chain(**overrides: object) -> ChainRequest:
    document: dict[str, object] = {
        "steps": [
            {"id": "first", "process": {"id": PRODUCER_ID}, "inputs": {"value": 1}},
            {
                "id": "second",
                "process": {"id": CONSUMER_ID},
                "inputs": {},
                "links": [{"member": "source", "step": "first", "output": "thing"}],
            },
        ]
    }
    document.update(overrides)
    return ChainRequest.model_validate(document)


class _Runner:
    """A runner that writes the artefact and the outcome a real one would.

    Records the directories it was handed, so a test can assert what never ran.
    """

    def __init__(
        self,
        *,
        produces: bool = True,
        fails_on: str | None = None,
        warns: str | None = None,
        silent_exit: int | None = None,
        lies: bool = False,
    ) -> None:
        self.produces = produces
        self.fails_on = fails_on
        self.warns = warns
        self.silent_exit = silent_exit
        self.lies = lies
        self.calls: list[str] = []

    def __call__(self, capability_id: str, job_dir: Path) -> tuple[int, str]:
        self.calls.append(job_dir.name)
        if self.silent_exit is not None:
            return self.silent_exit, ""
        failed = self.fails_on is not None and self.fails_on in job_dir.name
        if self.produces and not failed:
            artefact = job_dir / THING_PATH
            artefact.parent.mkdir(parents=True, exist_ok=True)
            artefact.write_bytes(b"artefact")
        outcome = {
            "job_id": f"sha256:{job_dir.name}",
            "process": {"id": capability_id, "version": "1.0.0"},
            "status": "failed" if failed else "successful",
            "exit_code": 21 if failed else 0,
            "reused": False,
        }
        if failed:
            outcome["errors"] = [{"code": "HMPY.E000", "detail": "the step said no"}]
        if self.warns is not None:
            outcome["warnings"] = [self.warns]
        if self.lies:
            outcome["status"] = "failed"
        (job_dir / "outcome.json").write_text(json.dumps(outcome), encoding="utf-8")
        return (21 if failed else 0), json.dumps(outcome)


def _run(
    root: Path, chain: ChainRequest | None = None, **runner_options: object
) -> tuple[ChainOutcome, _Runner]:
    run_step = _Runner(**runner_options)  # type: ignore[arg-type]
    outcome = run_chain(
        chain if chain is not None else _chain(),
        root,
        declaration=_declaration,
        run_step=run_step,
        exit_code_for=lambda _exc: 14,
    )
    return outcome, run_step


def test_the_second_step_reads_the_artefact_the_first_wrote(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path)

    written = json.loads((tmp_path / "02-second" / "request.json").read_text(encoding="utf-8"))
    assert written["inputs"]["source"] == {
        "href": str(tmp_path / "01-first" / THING_PATH),
        "type": THING_MEDIA_TYPE,
    }
    assert outcome.exit_code == 0
    assert outcome.document["status"] == "successful"


def test_the_link_is_absolute_because_a_relative_one_leaves_the_job_directory(
    tmp_path: Path,
) -> None:
    """The reason the chain writes a full path, asserted against the refusal itself."""
    _run(tmp_path)
    job = JobDirectory.open(tmp_path / "02-second")
    written = json.loads(job.request_path.read_text(encoding="utf-8"))

    assert job.resolve_input(
        written["inputs"]["source"]["href"], loc=("inputs", "source")
    ).is_file()
    with pytest.raises(ConfigValidationError):
        job.resolve_input(f"../01-first/{THING_PATH}", loc=("inputs", "source"))


def test_the_report_names_the_step_directory_and_the_job_of_each(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path)

    steps = outcome.document["steps"]
    assert [step["dir"] for step in steps] == ["01-first", "02-second"]
    assert [step["job_id"] for step in steps] == ["sha256:01-first", "sha256:02-second"]
    assert steps[1]["inputs_from"] == [
        {
            "member": "source",
            "step": "first",
            "output": "thing",
            "path": f"01-first/{THING_PATH}",
            "type": THING_MEDIA_TYPE,
        }
    ]


def test_the_report_is_on_disk_and_is_what_the_caller_is_handed(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path)

    on_disk = json.loads((tmp_path / CHAIN_OUTCOME_FILENAME).read_text(encoding="utf-8"))
    assert on_disk == outcome.document


def test_a_failing_step_stops_the_chain_and_the_rest_never_runs(tmp_path: Path) -> None:
    outcome, run_step = _run(tmp_path, fails_on="first")

    assert outcome.exit_code == 21
    assert outcome.document["status"] == "failed"
    assert [step["status"] for step in outcome.document["steps"]] == ["failed", "skipped"]
    assert run_step.calls == ["01-first"]
    assert not (tmp_path / "02-second").exists()


def test_a_declared_artefact_the_run_did_not_write_refuses_the_reader(tmp_path: Path) -> None:
    outcome, run_step = _run(tmp_path, produces=False)

    assert run_step.calls == ["01-first"]
    assert outcome.exit_code == 14
    second = outcome.document["steps"][1]
    assert second["status"] == "failed"
    assert "did not produce" in json.dumps(second["errors"])
    # Refused before the directory exists, so nothing half-staged is left.
    assert not (tmp_path / "02-second").exists()


def test_a_relative_root_still_writes_an_absolute_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guarantee is the function's, not the caller's."""
    monkeypatch.chdir(tmp_path)

    _run(Path("."))

    written = json.loads((tmp_path / "02-second" / "request.json").read_text(encoding="utf-8"))
    assert Path(written["inputs"]["source"]["href"]).is_absolute()
    assert Path(written["inputs"]["source"]["href"]).is_file()


def test_a_step_that_published_no_document_is_read_off_its_exit_code(tmp_path: Path) -> None:
    """130 says dismissed. A cancellation is not a failure of the work."""
    outcome, _ = _run(tmp_path, silent_exit=130)

    assert outcome.exit_code == 130
    assert outcome.document["status"] == "dismissed"
    assert outcome.document["steps"][0]["status"] == "dismissed"
    assert outcome.document["steps"][1]["status"] == "skipped"


def test_a_document_that_contradicts_its_exit_code_is_published_not_believed(
    tmp_path: Path,
) -> None:
    """The exit code decides, and the disagreement is a fault of the runner.

    Copying the stated status produced the one report nobody can act on: a
    chain saying ``failed`` beside ``"exit_code": 0``, which is exactly the
    contradiction ``JobOutcome`` refuses one layer down.
    """
    outcome, _ = _run(tmp_path, lies=True)

    assert outcome.exit_code == 0
    assert outcome.document["status"] == "successful"
    first = outcome.document["steps"][0]
    assert first["status"] == "successful"
    assert "the exit code decides" in json.dumps(first["errors"])


def test_a_root_that_cannot_hold_its_report_is_refused_before_anything_runs(
    tmp_path: Path,
) -> None:
    """A chain that ran two jobs and then cannot report is the worst outcome."""
    (tmp_path / CHAIN_OUTCOME_FILENAME).mkdir()

    with pytest.raises(JobUsageError, match=CHAIN_OUTCOME_FILENAME):
        _run(tmp_path)

    assert not (tmp_path / "01-first").exists()


def test_the_report_repeats_what_each_step_warned(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, warns="request targets 1.0.1; this build carries 1.0.0")

    assert outcome.document["steps"][0]["warnings"] == [
        "request targets 1.0.1; this build carries 1.0.0"
    ]


def test_every_declared_step_is_accounted_for_even_unrun(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, fails_on="first")

    assert [step["id"] for step in outcome.document["steps"]] == ["first", "second"]
    assert outcome.document["steps"][1]["exit_code"] is None


def test_a_capability_this_build_does_not_serve_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    chain = ChainRequest.model_validate(
        {"steps": [{"id": "only", "process": {"id": "no-such-capability"}}]}
    )

    with pytest.raises(ConfigValidationError) as excinfo:
        _run(tmp_path, chain)

    assert excinfo.value.details[0]["pointer"] == "/steps/0/process/id"
    assert list(tmp_path.iterdir()) == []


def test_an_output_the_producer_does_not_declare_is_refused() -> None:
    chain = _chain(
        steps=[
            {"id": "first", "process": {"id": PRODUCER_ID}},
            {
                "id": "second",
                "process": {"id": CONSUMER_ID},
                "links": [{"member": "source", "step": "first", "output": "nothing"}],
            },
        ]
    )

    with pytest.raises(ConfigValidationError) as excinfo:
        resolve_chain(chain, declaration=_declaration)

    assert excinfo.value.details[0]["pointer"] == "/steps/1/links/0/output"


def test_a_major_version_the_build_does_not_carry_is_refused() -> None:
    chain = ChainRequest.model_validate(
        {"steps": [{"id": "only", "process": {"id": PRODUCER_ID, "version": "2.0.0"}}]}
    )

    with pytest.raises(Exception, match="2.0.0"):
        resolve_chain(chain, declaration=_declaration)


@pytest.mark.parametrize(
    ("steps", "message"),
    [
        (
            [
                {"id": "same", "process": {"id": PRODUCER_ID}},
                {"id": "SAME", "process": {"id": CONSUMER_ID}},
            ],
            "repeat the id",
        ),
        (
            [
                {
                    "id": "first",
                    "process": {"id": CONSUMER_ID},
                    "links": [{"member": "source", "step": "second", "output": "thing"}],
                },
                {"id": "second", "process": {"id": PRODUCER_ID}},
            ],
            "does not run before it",
        ),
        (
            [
                {"id": "first", "process": {"id": PRODUCER_ID}},
                {
                    "id": "second",
                    "process": {"id": CONSUMER_ID},
                    "inputs": {"source": {"href": "/elsewhere"}},
                    "links": [{"member": "source", "step": "first", "output": "thing"}],
                },
            ],
            "given once",
        ),
        (
            [
                {"id": "first", "process": {"id": PRODUCER_ID}},
                {
                    "id": "second",
                    "process": {"id": CONSUMER_ID},
                    "links": [
                        {"member": "source", "step": "first", "output": "thing"},
                        {"member": "source", "step": "first", "output": "thing"},
                    ],
                },
            ],
            "twice",
        ),
        (
            [
                {
                    "id": "itself",
                    "process": {"id": CONSUMER_ID},
                    "links": [{"member": "source", "step": "itself", "output": "thing"}],
                }
            ],
            "does not run before it",
        ),
    ],
    ids=["repeated-id", "forward-link", "member-given-twice", "member-linked-twice", "self-link"],
)
def test_a_document_no_sequential_run_could_satisfy_is_refused(
    steps: list[dict], message: str
) -> None:
    with pytest.raises(Exception, match=message):
        ChainRequest.model_validate({"steps": steps})


def test_an_unknown_member_of_the_document_is_refused(tmp_path: Path) -> None:
    path = tmp_path / CHAIN_FILENAME
    path.write_text(
        json.dumps(
            {
                "steps": [{"id": "only", "process": {"id": PRODUCER_ID}}],
                "parallel": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match="parallel"):
        read_chain(path)


def test_a_document_that_is_not_json_is_refused_where_it_broke(tmp_path: Path) -> None:
    path = tmp_path / CHAIN_FILENAME
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="line 1"):
        read_chain(path)


def test_a_byte_order_mark_is_read_and_not_refused(tmp_path: Path) -> None:
    path = tmp_path / CHAIN_FILENAME
    path.write_text(
        json.dumps({"steps": [{"id": "only", "process": {"id": PRODUCER_ID}}]}),
        encoding="utf-8-sig",
    )

    assert read_chain(path).steps[0].id == "only"


def test_the_two_capabilities_of_this_build_chain_on_the_watershed(tmp_path: Path) -> None:
    """The contract of the phase, against the real declarations.

    ``data-fetch`` takes its extent as an input, and a mask already produced is
    one of the three spellings it accepts. What the chain has to get right is
    which artefact of the first step is that mask, and it reads that from the
    declaration rather than from a string written here.
    """
    from hydromodpy.data.fetch.capability import DATA_FETCH
    from hydromodpy.spatial.site_selection.hydrology.capability import (
        TERRAIN_DELINEATE,
        WATERSHED_VECTOR_PATH,
    )

    served = {DATA_FETCH.id: DATA_FETCH, TERRAIN_DELINEATE.id: TERRAIN_DELINEATE}
    chain = ChainRequest.model_validate(
        {
            "steps": [
                {
                    "id": "delineate",
                    "process": {"id": TERRAIN_DELINEATE.id, "version": "1.0.0"},
                    "inputs": {
                        "dem": {"href": "/data/dem.tif"},
                        "outlets": [{"site_id": "valley", "x": 300112.5, "y": 6701262.5}],
                        "crs_project": "EPSG:2154",
                    },
                },
                {
                    "id": "fetch",
                    "process": {"id": DATA_FETCH.id},
                    "inputs": {"source": {"id": "ign-bdalti"}},
                    "links": [
                        {"member": "mask", "step": "delineate", "output": "watershed_vector"}
                    ],
                },
            ]
        }
    )

    resolved = resolve_chain(chain, declaration=served.get)

    assert resolved[1].links[0].path == f"01-delineate/{WATERSHED_VECTOR_PATH}"
    assert resolved[1].links[0].media_type == "application/geopackage+sqlite3"


def test_the_terrain_and_the_domain_chain_on_the_corrected_dem_and_the_watershed() -> None:
    """The contract F7e was opened for, against the real declarations.

    What the audit called missing between terrain and mesh is a capability
    whose inputs are artefacts the delineation already seals: the corrected DEM
    is the top surface of the domain, and the catchment polygon is what bounds
    it. The two links are read off the declarations rather than off a path
    written here, so renaming an output on either side lands in this test.
    """
    from hydromodpy.spatial.domain.capability import DOMAIN_BUILD
    from hydromodpy.spatial.site_selection.hydrology.capability import (
        DEM_CORRECTED_PATH,
        TERRAIN_DELINEATE,
        WATERSHED_VECTOR_PATH,
    )

    served = {DOMAIN_BUILD.id: DOMAIN_BUILD, TERRAIN_DELINEATE.id: TERRAIN_DELINEATE}
    chain = ChainRequest.model_validate(
        {
            "steps": [
                {
                    "id": "delineate",
                    "process": {"id": TERRAIN_DELINEATE.id, "version": "1.0.0"},
                    "inputs": {
                        "dem": {"href": "/data/dem.tif"},
                        "outlets": [{"site_id": "valley", "x": 300112.5, "y": 6701262.5}],
                        "crs_project": "EPSG:2154",
                    },
                },
                {
                    "id": "domain",
                    "process": {"id": DOMAIN_BUILD.id},
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
        }
    )

    resolved = resolve_chain(chain, declaration=served.get)

    assert resolved[1].links[0].path == f"01-delineate/{DEM_CORRECTED_PATH}"
    assert resolved[1].links[1].path == f"01-delineate/{WATERSHED_VECTOR_PATH}"
    assert resolved[1].links[1].media_type == "application/geopackage+sqlite3"
