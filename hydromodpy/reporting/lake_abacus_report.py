"""Render the lake abacus comparison from a built model's reconstruction stash.

When a lake uses ``bed_reconstruction``, the MF6 build stashes the reference and
simulated abacus on ``model._lake_bed_reconstruction``. This helper turns that
stash into the comparison figure, one PNG per lake, so a user who built a model
in Python can request the diagnostic without re-deriving anything.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["plot_lake_abacus_comparison_for_model"]


def plot_lake_abacus_comparison_for_model(
    model: object,
    *,
    figures_dir: str | Path,
    lake_id: str | None = None,
    stage_unit: str = "m",
    volume_unit: str = "m3",
    area_unit: str = "m2",
) -> dict[str, dict]:
    """Render the abacus comparison for each reconstructed lake on ``model``.

    Returns ``{lake_id: {"figure": path, "metrics": {...}}}``. Lakes without a
    simulated abacus (reconstruction ran without an abacus) are skipped. Returns
    an empty mapping when no lake bed was reconstructed.
    """
    from hydromodpy.display.figures.lake_abacus_comparison import plot_lake_abacus_comparison

    reconstruction = getattr(model, "_lake_bed_reconstruction", None) or {}
    if not reconstruction:
        return {}

    figures_dir = Path(figures_dir)
    lake_ids = [lake_id] if lake_id is not None else list(reconstruction)

    results: dict[str, dict] = {}
    for current in lake_ids:
        record = reconstruction.get(current)
        if record is None or record.get("sim_volume") is None:
            continue
        safe = "".join(ch if ch.isalnum() else "_" for ch in str(current))
        out_path = figures_dir / f"lake_abacus_{safe}.png"
        metrics = plot_lake_abacus_comparison(
            record["abacus_stage"],
            record["abacus_volume"],
            record["abacus_sarea"],
            record["sim_volume"],
            record["sim_sarea"],
            out_path=out_path,
            lake_id=str(current),
            stage_unit=stage_unit,
            volume_unit=volume_unit,
            area_unit=area_unit,
        )
        results[str(current)] = {"figure": str(out_path), "metrics": metrics}
    return results
