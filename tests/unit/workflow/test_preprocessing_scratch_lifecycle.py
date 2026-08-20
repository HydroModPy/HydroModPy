"""Lifetime of ``.hmp/scratch/_preprocessing``.

The tree holds the corrected DEM and the flow rasters: hundreds of MB, written
once and then ingested into the project store. Every trial of a calibration
session reads it, so no trial may delete it; but only a *promoted* run reaches
the export step that normally does, so a session that promotes nothing used to
leave the whole tree behind.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.runners.cli_runner import _release_session_scratch
from hydromodpy.spatial.geographic.store_ingestion import cleanup_stable_folder
from hydromodpy.workflow.steps.export import step_cleanup_preprocessing


@pytest.fixture
def preprocessing_tree(tmp_path):
    """A populated ``_preprocessing`` tree and the geographic object naming it."""
    stable = tmp_path / ".hmp" / "scratch" / "_preprocessing"
    (stable / "geographic").mkdir(parents=True)
    (stable / "demcorrecflow").mkdir(parents=True)
    (stable / "geographic" / "watershed.tif").write_bytes(b"x" * 4096)
    (stable / "demcorrecflow" / "dem_breach.tif").write_bytes(b"y" * 8192)
    return stable, SimpleNamespace(stable_folder=str(stable))


def _ctx(geographic: object, *, write_intermediates: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        setup=SimpleNamespace(geographic=geographic),
        cfg=SimpleNamespace(geographic=SimpleNamespace(write_intermediates=write_intermediates)),
    )


def _trial_ctx(geographic: object, *, write_intermediates: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        ctx=SimpleNamespace(setup=SimpleNamespace(geographic=geographic)),
        base_cfg=SimpleNamespace(
            geographic=SimpleNamespace(write_intermediates=write_intermediates)
        ),
    )


def test_cleanup_reports_the_bytes_it_frees(preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree

    freed = cleanup_stable_folder(geographic)

    assert freed == 4096 + 8192
    assert not stable.exists()


def test_keeping_the_intermediates_keeps_the_tree(preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree

    assert cleanup_stable_folder(geographic, keep=True) == 0
    assert stable.is_dir()


def test_cleanup_is_idempotent(preprocessing_tree) -> None:
    _, geographic = preprocessing_tree
    cleanup_stable_folder(geographic)

    assert cleanup_stable_folder(geographic) == 0


def test_export_step_drops_the_tree(preprocessing_tree) -> None:
    """The solver scratch can be redirected elsewhere; this tree cannot."""
    stable, geographic = preprocessing_tree

    freed = step_cleanup_preprocessing(_ctx(geographic))

    assert freed > 0
    assert not stable.exists()


def test_export_step_honours_write_intermediates(preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree

    assert step_cleanup_preprocessing(_ctx(geographic, write_intermediates=True)) == 0
    assert stable.is_dir()


def test_export_step_without_geographic_does_nothing() -> None:
    assert step_cleanup_preprocessing(_ctx(None)) == 0


def test_a_session_that_promotes_nothing_still_drops_the_tree(preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree

    _release_session_scratch(_trial_ctx(geographic))

    assert not stable.exists()


def test_a_session_keeps_the_tree_on_request(monkeypatch, preprocessing_tree) -> None:
    stable, geographic = preprocessing_tree
    monkeypatch.setenv("HMP_KEEP_TRIAL_SCRATCH", "1")

    _release_session_scratch(_trial_ctx(geographic))

    assert stable.is_dir()


def test_a_session_cleanup_failure_never_propagates(monkeypatch, preprocessing_tree) -> None:
    """It runs in a ``finally``: raising there would mask the real error."""
    _, geographic = preprocessing_tree

    def boom(*_args, **_kwargs):
        raise OSError("device busy")

    monkeypatch.setattr("hydromodpy.spatial.geographic.store_ingestion.cleanup_stable_folder", boom)
    _release_session_scratch(_trial_ctx(geographic))


def test_a_session_without_geographic_does_nothing() -> None:
    _release_session_scratch(_trial_ctx(None))


def test_the_tree_outlives_a_single_trial(preprocessing_tree) -> None:
    """Trials share it: only the end of the session may drop it."""
    from hydromodpy.calibration.runners.sandbox import TrialSandbox

    stable, _ = preprocessing_tree
    scratch = stable.parent
    with TrialSandbox("run", 1, solver_scratch_folder=scratch) as sandbox:
        trial_dir = Path(scratch) / sandbox.model_name
        trial_dir.mkdir(parents=True)
        (trial_dir / "mfsim.nam").write_text("x")

    assert not trial_dir.exists()
    assert stable.is_dir()
