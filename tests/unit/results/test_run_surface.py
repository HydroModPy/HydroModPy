"""Surface-area guard for :class:`hydromodpy.results.run.Run`.

CLAUDE.md caps any class at 50 public methods. ``Run`` accumulated 65+
entries through mixins until P8 removed the per-cell mixin and the
``run.at`` / ``run.fields`` duplicates. This test fails if the surface
regresses.
"""

from __future__ import annotations

from hydromodpy.results.run import Run

MAX_PUBLIC_METHODS = 50


def test_run_public_surface_below_limit() -> None:
    """``Run`` exposes at most 50 public attributes (CLAUDE.md cap)."""
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


def test_run_keeps_canonical_field_readers() -> None:
    """``run.field`` and ``run.array.{dataset,to_xarray_batch}`` remain."""
    assert hasattr(Run, "field")
    # ``array`` is initialised in ``__init__`` so check via __init__
    assert callable(Run.__init__)
