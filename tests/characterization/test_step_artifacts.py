"""What the journal knows about the twelve steps of a finished run.

Finding A1: the six steps that build the model - ``validate``, ``resolve``,
``build_geographic``, ``load_data``, ``build_mesh``, ``setup_process`` - declare
no durable artefact. Four later steps do (``prepare_solver``, ``run_solver``,
``extract``, ``export``), so the contract exists and is simply not honoured by
the head of the pipeline. The consequence is observable without reading any
source: after a real run the journal holds no row at all for those six steps,
so a resume has nothing to rebuild from and replays them.

Phase F7 gives the six an ``artifacts()`` and a ``rebuild_state()`` that reads
the disk. The day it lands, this strict xfail becomes a failure.
"""

from __future__ import annotations

import pytest

from tests.characterization.conftest import ProducedRun

MODEL_BUILD_STEPS = (
    "validate",
    "resolve",
    "build_geographic",
    "load_data",
    "build_mesh",
    "setup_process",
)

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


@pytest.mark.xfail(strict=True, reason="A1: the six model-build steps declare no artefact")
def test_every_step_of_a_run_declares_what_it_left_on_disk(produced_run: ProducedRun) -> None:
    """The journal records the twelve steps, and each names its durable outputs."""
    rows = _journal_rows(produced_run)

    missing = [name for name in MODEL_BUILD_STEPS + SOLVE_STEPS if name not in rows]
    assert not missing, f"steps absent from the journal: {missing}"

    without_artifacts = [
        name
        for name in MODEL_BUILD_STEPS
        if not rows[name]["artifact_uris"]
        or str(rows[name]["outputs_hash"]).startswith(EMPTY_DIGEST_PREFIX)
    ]
    assert not without_artifacts, f"steps that rebuild from nothing: {without_artifacts}"


def test_the_solving_steps_already_declare_their_artefacts(produced_run: ProducedRun) -> None:
    """The half of the pipeline that honours the contract keeps honouring it."""
    rows = _journal_rows(produced_run)
    for name in ("prepare_solver", "run_solver", "extract"):
        assert name in rows, f"{name} absent from the journal"
        assert rows[name]["artifact_uris"], f"{name} declares no artefact"
