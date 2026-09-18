"""What the journal knows about the twelve steps of a finished run.

Finding A1 said the six steps that build the model - ``validate``, ``resolve``,
``build_geographic``, ``load_data``, ``build_mesh``, ``setup_process`` - declare
no durable artefact, while four later steps do, so the contract existed and was
simply not honoured by the head of the pipeline. After a real run the journal
held no row at all for those six, and a resume had nothing to rebuild from.

Phase F7 closed that, and measuring it changed the claim. Three of the six have
a durable product and now name it: the resolved configuration for ``validate``,
the delineated tree for ``build_geographic``, the description of what was bound
for ``load_data``. The other three leave nothing, and that is the honest
answer rather than a gap - see D172. ``resolve`` builds a data plan in memory
whose result is already on disk inside the document ``load_data`` writes;
``setup_process`` instantiates the flow and transport objects from a domain
that is already described; and ``build_mesh`` writes a mesh only when
``[mesh_catchment]`` asks for one, which the project below does not.

So the assertion is no longer "all six declare". It is: every step of a run has
a row, every step with a durable product declares it, and the three that leave
nothing are named here. A step that starts or stops declaring turns this red,
which is the point - the list is a measurement, not a tolerance.
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
DECLARING_HEAD_STEPS = ("validate", "build_geographic", "load_data")

# The head steps that leave nothing on this project, and why. D172.
SILENT_HEAD_STEPS = {
    "resolve": "builds a data plan in memory; load_data's document carries its result",
    "build_mesh": "meshes only under [mesh_catchment], which this project does not declare",
    "setup_process": "instantiates flow and transport from a domain already described",
}

SOLVE_STEPS = ("prepare_solver", "run_solver", "extract", "derive", "display", "export")

# sha256 of the empty byte string: what the journal writes when a step declares
# no artefact at all.
EMPTY_DIGEST_PREFIX = "e3b0c44298fc1c14"


def _journal_rows(produced_run: ProducedRun) -> dict[str, dict[str, object]]:
    """Return the journal row of every step of the run, keyed by step name."""
    import duckdb

    index = produced_run.workspace / ".hmp" / "index.duckdb"
    assert index.is_file(), f"no index at {index}"
    connection = duckdb.connect(str(index), read_only=True)
    try:
        frame = connection.execute(
            "SELECT step_name, step_order, outputs_hash, artifact_uris "
            "FROM workflow_steps WHERE run_id = ?",
            [produced_run.run_name],
        ).fetchdf()
    finally:
        connection.close()
    return {row["step_name"]: dict(row) for _, row in frame.iterrows()}


def test_every_step_of_a_run_declares_what_it_left_on_disk(produced_run: ProducedRun) -> None:
    """The journal records the twelve steps, and each names its durable outputs."""
    rows = _journal_rows(produced_run)

    missing = [name for name in MODEL_BUILD_STEPS + SOLVE_STEPS if name not in rows]
    assert not missing, f"steps absent from the journal: {missing}"

    without_artifacts = [
        name
        for name in DECLARING_HEAD_STEPS
        if not rows[name]["artifact_uris"]
        or str(rows[name]["outputs_hash"]).startswith(EMPTY_DIGEST_PREFIX)
    ]
    assert not without_artifacts, f"steps that rebuild from nothing: {without_artifacts}"


def test_the_three_head_steps_that_leave_nothing_are_the_measured_three(
    produced_run: ProducedRun,
) -> None:
    """The list of steps with no durable product is a measurement, not a tolerance."""
    rows = _journal_rows(produced_run)

    silent = {
        name
        for name in MODEL_BUILD_STEPS
        if not rows[name]["artifact_uris"]
        or str(rows[name]["outputs_hash"]).startswith(EMPTY_DIGEST_PREFIX)
    }
    assert silent == set(SILENT_HEAD_STEPS), (
        "the head steps that leave nothing moved; update SILENT_HEAD_STEPS and say why"
    )


def test_the_solving_steps_already_declare_their_artefacts(produced_run: ProducedRun) -> None:
    """The half of the pipeline that honours the contract keeps honouring it."""
    rows = _journal_rows(produced_run)
    for name in ("prepare_solver", "run_solver", "extract"):
        assert name in rows, f"{name} absent from the journal"
        assert rows[name]["artifact_uris"], f"{name} declares no artefact"
