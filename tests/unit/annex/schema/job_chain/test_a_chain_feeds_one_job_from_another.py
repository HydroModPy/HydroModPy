"""Two capabilities compose through the disk, and the chain is what writes it.

The mechanics are checked against declarations built here, because the chain
knows no capability and asserting it against the ones this build ships would
hide that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.schema.capability import CapabilityDecl, OutputDecl
from hydromodpy_annex.schema.job_chain.chain import (
    CHAIN_FILENAME,
    CHAIN_OUTCOME_FILENAME,
    ChainOutcome,
    ChainRequest,
    read_chain,
    resolve_chain,
    run_chain,
)

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
    """A runner that writes the artifact and the outcome a real one would.

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


@pytest.mark.parametrize(
    "inputs",
    [{"extent": {"mask": {"href": "/elsewhere"}}}, {"extent": "a string, not an object"}],
    ids=["nested-member-given", "parent-not-an-object"],
)
def test_a_dotted_member_the_inputs_already_fill_is_refused(inputs: dict) -> None:
    with pytest.raises(Exception, match="given once"):
        ChainRequest.model_validate(
            {
                "steps": [
                    {"id": "first", "process": {"id": PRODUCER_ID}},
                    {
                        "id": "second",
                        "process": {"id": CONSUMER_ID},
                        "inputs": inputs,
                        "links": [{"member": "extent.mask", "step": "first", "output": "thing"}],
                    },
                ]
            }
        )


def test_the_report_is_on_disk_and_is_what_the_caller_is_handed(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path)

    on_disk = json.loads((tmp_path / CHAIN_OUTCOME_FILENAME).read_text(encoding="utf-8"))
    assert on_disk == outcome.document


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


def test_a_byte_order_mark_is_read_and_not_refused(tmp_path: Path) -> None:
    path = tmp_path / CHAIN_FILENAME
    path.write_text(
        json.dumps({"steps": [{"id": "only", "process": {"id": PRODUCER_ID}}]}),
        encoding="utf-8-sig",
    )

    assert read_chain(path).steps[0].id == "only"
