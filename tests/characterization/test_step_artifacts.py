"""What the journal knows about the eleven steps that precede the seal.

Finding A1 said the six steps that build the model - ``validate``, ``resolve``,
``build_geographic``, ``load_data``, ``build_mesh``, ``setup_process`` - declare
no durable artifact, while four later steps do, so the contract existed and was
simply not honored by the head of the pipeline. After a real run the journal
held no row at all for those six, and a resume had nothing to rebuild from.

Phase F7 closed that, and measuring it changed the claim. Four of the six have
a durable product and now name it: the resolved configuration for ``validate``,
the delineated tree for ``build_geographic``, the description of what was bound
for ``load_data``, the stored mesh for ``build_mesh``. The other two leave
nothing, and that is the honest answer rather than a gap - see D172.
``resolve`` builds a data plan in memory whose result is already on disk
inside the document ``load_data`` writes, and ``setup_process`` instantiates
the flow and transport objects from a domain that is already described.
``build_mesh`` once left nothing, but every engine now goes through the
product store, so it names the mesh product it stored.

So the assertion is no longer "all six declare". It is: every step of a run has
a row, every step with a durable product declares it, and the two that leave
nothing are named here. A step that starts or stops declaring turns this red,
which is the point - the list is a measurement, not a tolerance.

The journal is ``<run>/.hmp/checkpoints/steps.json``, the attempt state of the
run, and no longer an index table. The seal of a completed run removes it with
the rest of ``<run>/.hmp/``, so the run read here is stopped after ``export``,
the last step before the seal. The ``display`` step follows the seal, so this
journal has no row for it.
"""

from __future__ import annotations

from tests.characterization.conftest import ProducedRun

MODEL_BUILD_STEPS = (
    "validate",
    "resolve",
    "build_geographic",
    "load_data",
    "build_mesh",
    "setup_process",
)

# The head steps that leave a durable product of their own.
DECLARING_HEAD_STEPS = ("validate", "build_geographic", "load_data", "build_mesh")

# The head steps that leave nothing on this project, and why. D172.
SILENT_HEAD_STEPS = {
    "resolve": "builds a data plan in memory; load_data's document carries its result",
    "setup_process": "instantiates flow and transport from a domain already described",
}

SOLVE_STEPS = ("prepare_solver", "run_solver", "extract", "derive", "export")

# sha256 of the empty byte string: what the journal writes when a step declares
# no artifact at all.
EMPTY_DIGEST_PREFIX = "e3b0c44298fc1c14"


def _journal_rows(run: ProducedRun) -> dict[str, dict[str, object]]:
    """Return the journal row of every step of the run, keyed by step name."""
    from hydromodpy.workflow.record.journal import WorkflowJournal

    journal = WorkflowJournal(run.run_dir)
    assert journal.path.is_file(), f"no journal at {journal.path}"
    return {
        row.step_name: {
            "step_order": row.step_order,
            "status": row.status,
            "outputs_hash": row.outputs_hash,
            "artifact_uris": row.artifact_uris,
        }
        for row in journal.list_steps(run.run_name)
    }


def test_every_step_of_a_run_declares_what_it_left_on_disk(
    run_before_its_seal: ProducedRun,
) -> None:
    """The journal records the eleven steps, and each names its durable outputs."""
    rows = _journal_rows(run_before_its_seal)

    missing = [name for name in MODEL_BUILD_STEPS + SOLVE_STEPS if name not in rows]
    assert not missing, f"steps absent from the journal: {missing}"
    unfinished = [name for name, row in rows.items() if row["status"] != "completed"]
    assert not unfinished, f"steps the journal does not close: {unfinished}"

    without_artifacts = [
        name
        for name in DECLARING_HEAD_STEPS
        if not rows[name]["artifact_uris"]
        or str(rows[name]["outputs_hash"]).startswith(EMPTY_DIGEST_PREFIX)
    ]
    assert not without_artifacts, f"steps that rebuild from nothing: {without_artifacts}"


def test_the_two_head_steps_that_leave_nothing_are_the_measured_two(
    run_before_its_seal: ProducedRun,
) -> None:
    """The list of steps with no durable product is a measurement, not a tolerance."""
    rows = _journal_rows(run_before_its_seal)

    silent = {
        name
        for name in MODEL_BUILD_STEPS
        if not rows[name]["artifact_uris"]
        or str(rows[name]["outputs_hash"]).startswith(EMPTY_DIGEST_PREFIX)
    }
    assert silent == set(SILENT_HEAD_STEPS), (
        "the head steps that leave nothing moved; update SILENT_HEAD_STEPS and say why"
    )


def test_the_solving_steps_already_declare_their_artefacts(
    run_before_its_seal: ProducedRun,
) -> None:
    """The half of the pipeline that honors the contract keeps honoring it."""
    rows = _journal_rows(run_before_its_seal)
    for name in ("prepare_solver", "run_solver", "extract"):
        assert name in rows, f"{name} absent from the journal"
        assert rows[name]["artifact_uris"], f"{name} declares no artefact"
