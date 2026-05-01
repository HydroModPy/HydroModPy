"""Well-resolution helpers for the Boussinesq forcing resolver."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from hydromodpy.core.units.volumetric_flow import (
    convert_to_m3_per_s,
    normalize_m3_per_s_unit,
)


class WellResolutionMixin:
    """Resolve localized wells to cell-wise flux vectors."""

    mesh: object
    flow: object
    time_grid: object

    def resolve_well_flux_by_period(self, nper: int) -> np.ndarray:
        """Resolve all localized well fluxes to one cell vector per period."""
        active = tuple(getattr(self.flow, "active_sinks_sources", ()) or ())
        if "wells" not in active:
            return np.zeros((nper, self.mesh.n_cells), dtype=float)

        sinks_sources = getattr(self.flow, "sinks_sources", {})
        wells = sinks_sources.get("wells", {}) if isinstance(sinks_sources, Mapping) else {}
        if not isinstance(wells, Mapping) or not wells:
            return np.zeros((nper, self.mesh.n_cells), dtype=float)

        by_period = np.zeros((nper, self.mesh.n_cells), dtype=float)
        for well_id, well_cfg in wells.items():
            cell_index = self.resolve_well_cell_index(str(well_id), well_cfg)
            flux_series = self.resolve_well_flux_series(str(well_id), well_cfg, nper)
            by_period[:, cell_index] += flux_series
        return by_period

    def resolve_well_cell_index(self, well_id: str, well_cfg: object) -> int:
        """Project one well location to one cell of the triangular mesh."""
        layer = getattr(well_cfg, "layer", 0)
        if layer is not None and int(layer) != 0:
            raise NotImplementedError(
                f"Well '{well_id}' targets layer={int(layer)} but the current "
                "boussinesq backend is 2D and supports only layer 0."
            )

        cell_payload = getattr(well_cfg, "cell", None)
        location_mode = str(getattr(well_cfg, "location_mode", "") or "").strip().lower()
        if cell_payload is not None or location_mode in {"", "cell"}:
            raise NotImplementedError(
                f"Well '{well_id}' uses structured-grid cell addressing. "
                "The current boussinesq backend on gmsh triangles supports "
                "only coordinate-based wells (absolute_xy or relative_xy)."
            )
        if location_mode == "absolute_xy":
            x_m = float(well_cfg.x)
            y_m = float(well_cfg.y)
        elif location_mode == "relative_xy":
            x_rel = float(well_cfg.x_rel)
            y_rel = float(well_cfg.y_rel)
            x_m = self.mesh.x_min_m + x_rel * (self.mesh.x_max_m - self.mesh.x_min_m)
            y_m = self.mesh.y_min_m + y_rel * (self.mesh.y_max_m - self.mesh.y_min_m)
        else:
            raise ValueError(f"Unsupported well location mode for '{well_id}': {location_mode!r}.")
        return self.mesh.locate_cell_index_for_point(x_m, y_m, allow_nearest=False)

    def resolve_well_flux_series(
        self,
        well_id: str,
        well_cfg: object,
        nper: int,
    ) -> np.ndarray:
        """Resolve one well rate to one value per period in m3/s."""
        forcing = getattr(well_cfg, "forcing", None)
        if forcing is not None:
            from hydromodpy.physics.flow.time_forcing import (
                resolve_period_values_from_forcing,
            )

            raw_values = resolve_period_values_from_forcing(
                forcing=forcing,
                simulation_window=getattr(self.time_grid, "window", None)
                if self.time_grid is not None
                else None,
                nper=int(nper),
                label=f"flow.sinks_sources.wells.{well_id}.forcing",
            )
            raw_units = getattr(forcing, "units", None) or getattr(well_cfg, "units", "m3/s")
            canonical_units = normalize_m3_per_s_unit(str(raw_units))
            values = np.asarray(
                [
                    convert_to_m3_per_s(
                        value,
                        unit=canonical_units,
                        label=f"flow.sinks_sources.wells.{well_id}.forcing[{idx}]",
                    )
                    for idx, value in enumerate(raw_values)
                ],
                dtype=float,
            )
            if not np.all(np.isfinite(values)):
                raise ValueError(f"flow.sinks_sources.wells.{well_id}.forcing must be finite.")
            return values
        return self.simple_period_series(
            getattr(well_cfg, "flux", None),
            nper=nper,
            label=f"flow.sinks_sources.wells.{well_id}.flux",
        )


__all__ = ["WellResolutionMixin"]
