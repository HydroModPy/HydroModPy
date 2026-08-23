"""The availability gate and the trial reader must answer on the same key.

``Run.has_table("calibration_iterations")`` asks the catalog on ``sim_id``. A
figure that decides it can render on that answer, then reads the trials some
other way, reports itself available and raises mid-render. That is exactly what
happened: the reader looked for an attribute no ``Run`` has, so four figures
were available and unrenderable on any real run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.calibration_trials import calibration_trials
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.run import Run

_CATALOG_TOML = """\
[workflow]
mode = "simulation"

[workspace]
root = "{root}"
project_root = "{root}"

[geographic]
source_mode = "synthetic"
"""

SIM_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def catalog(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(_CATALOG_TOML.format(root=tmp_path.as_posix()), encoding="utf-8")
    cat = Catalog.from_toml(path)
    try:
        yield cat
    finally:
        cat.close()


def _insert_trials(catalog, n: int) -> None:
    for iteration in range(n):
        catalog.backend.execute(
            """
            INSERT INTO calibration_iterations
                (session_id, iteration, sim_id, params_hash, parameters,
                 objective_value, metrics, status, from_cache, duration_s)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                SESSION_ID,
                iteration,
                SIM_ID,
                f"hash{iteration}",
                f'{{"K": {1e-5 * (iteration + 1)}}}',
                float(iteration),
                '{"J_signed": 1.0}',
                "completed",
                False,
                1.0,
            ],
        )


def test_the_gate_and_the_reader_agree_when_trials_exist(catalog) -> None:
    _insert_trials(catalog, 3)
    run = Run(SIM_ID, catalog)

    assert run.has_table("calibration_iterations") is True
    frame = calibration_trials(run)
    assert len(frame) == 3
    assert list(frame["iteration"]) == [0, 1, 2]


def test_the_gate_and_the_reader_agree_when_no_trial_exists(catalog) -> None:
    run = Run(SIM_ID, catalog)

    assert run.has_table("calibration_iterations") is False
    with pytest.raises(ValueError, match="no trial"):
        calibration_trials(run)


def test_a_promoted_run_reads_the_whole_session_it_came_from(catalog) -> None:
    """A figure about a calibration wants the calibration, not one trial.

    A promoted run carries the single row of the trial it was promoted from.
    Read by sim_id, the crossing of two distances and the trace of a bisection
    both came back as one point.
    """
    _insert_trials(catalog, 4)
    # The promoted run is a NEW simulation carrying one row of the same session;
    # (session_id, iteration) is the primary key, so it takes its own iteration.
    promoted = "44444444-4444-4444-4444-444444444444"
    catalog.backend.execute(
        """
        INSERT INTO calibration_iterations
            (session_id, iteration, sim_id, params_hash, parameters,
             objective_value, metrics, status, from_cache, duration_s)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [SESSION_ID, 9, promoted, "hash9", '{"K": 3e-05}', 2.0, "{}", "completed", False, 1.0],
    )

    frame = calibration_trials(Run(promoted, catalog))

    assert len(frame) == 5, "the promoted run must see the session, not its own row"
    assert set(frame["session_id"].astype(str)) == {SESSION_ID}


def test_a_session_filter_keeps_only_that_session(catalog) -> None:
    _insert_trials(catalog, 2)
    run = Run(SIM_ID, catalog)

    assert len(calibration_trials(run, session_id=SESSION_ID)) == 2
    with pytest.raises(ValueError, match="no trial"):
        calibration_trials(run, session_id="33333333-3333-3333-3333-333333333333")


def test_a_run_shaped_adapter_is_read_from_its_own_rows() -> None:
    # The calibration report builds one of these from a session journal, with
    # no catalog behind it; both carriers resolve to the same frame.
    class _Adapter:
        calibration_iterations = [{"iteration": 0, "objective_value": 1.0}]

    frame = calibration_trials(_Adapter())
    assert list(frame["iteration"]) == [0]


def test_anything_else_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="no calibration trial can be read"):
        calibration_trials(object())
