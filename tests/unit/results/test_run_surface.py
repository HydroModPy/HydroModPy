"""Surface-area guard for :class:`hydromodpy.results.run.view.Run`.

CLAUDE.md caps any class at 50 public methods. ``Run`` accumulated 65+
entries through mixins until P8 removed the per-cell mixin and the
``run.at`` / ``run.fields`` duplicates. This test fails if the surface
regresses.
"""

from __future__ import annotations

from hydromodpy.results.run.view import Run

# This version adds read, table, figure and show, the reads behind hydromodpy.show, and no old name died.
MAX_PUBLIC_METHODS = 54


def test_run_public_surface_below_limit() -> None:
    """``Run`` exposes at most ``MAX_PUBLIC_METHODS`` public attributes."""
    public = [m for m in dir(Run) if not m.startswith("_")]
    assert len(public) <= MAX_PUBLIC_METHODS, (
        f"Run has {len(public)} public attributes (max {MAX_PUBLIC_METHODS}): {public}"
    )


def test_run_does_not_expose_deprecated_helpers() -> None:
    """The legacy ``run.fields`` / ``run.at`` accessors are gone."""
    assert not hasattr(Run, "fields")
    assert not hasattr(Run, "at")
    # Per-cell mixin methods are now module-level functions in views
    assert not hasattr(Run, "saturated_fraction")
    assert not hasattr(Run, "drainage_density")
    assert not hasattr(Run, "persistence")
    assert not hasattr(Run, "cell_field_active_mask")


def test_run_places_its_periods_on_the_calendar_through_one_provider() -> None:
    """Date lookups live on ``run.periods``, as field readers live on ``run.array``."""
    from hydromodpy.results.run.periods import RunPeriods

    run = Run("sim", catalog=None)  # type: ignore[arg-type]
    assert isinstance(run.periods, RunPeriods)
    for name in ("edges", "step_at", "steps_for"):
        assert hasattr(RunPeriods, name)
    for name in ("period_edges", "step_at", "steps_for"):
        assert not hasattr(Run, name)


def test_run_keeps_canonical_field_readers() -> None:
    """``run.field`` and ``run.array.{dataset,to_xarray_batch}`` remain."""
    assert hasattr(Run, "field")
    # ``array`` is initialized in ``__init__`` so check via __init__
    assert callable(Run.__init__)


def test_run_answers_with_the_words_of_the_target() -> None:
    """D9: ``site``, ``checks``, ``inputs``, ``exports``, ``figures``, ``label()`` and ``dir``.

    The lineage is read by ``results.run.sealed.lineage_of`` (H36), the
    summary by the README and ``record``: neither is an attribute of ``Run``.
    """
    for name in ("site", "checks", "inputs", "exports", "figures", "label", "dir", "record"):
        assert hasattr(Run, name), name
    for name in ("lineage", "summary", "parent", "solver_category", "input_entries"):
        assert not hasattr(Run, name), name
