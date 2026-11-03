"""Output adapter for Boussinesq solver results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.budget_terms import BudgetKeep
from hydromodpy.core.logging import get_logger
from hydromodpy.core.scope import DOMAIN
from hydromodpy.core.units.time import CF_EPOCH, CF_TIME_UNITS, cf_time_axis_seconds
from hydromodpy.core.vertical_column import VERTICAL_LAYOUT_COLUMN_FRACTIONS
from hydromodpy.solver.boussinesq.export_payload import first_period_snapshot

logger = get_logger(__name__)


def _storage_flux(payload, *, first_snapshot: int, n_periods: int) -> np.ndarray | None:
    """Return the mean flux out of storage of each period, ``(n_periods, n_cells)`` in m3/s.

    MODFLOW signs it: positive when water leaves storage to enter the flow. It is
    the opposite of the temporal term of the transient residual, the change of
    the drainable volume ``area * Sy * max(h - z_bottom, 0)`` over the period. The
    volume is a state, so the steps of a period telescope to its two ends. On a
    cell with an imposed head the constant-head flux already holds that term. A
    first period solved steady starts from its own solution, so it changes nothing.
    ``None`` for a steady history, whose first snapshot closes a period.
    """
    if first_snapshot == 0:
        return None
    missing = [
        name
        for name in ("storage_coefficient", "z_bottom_m", "cell_area_m2")
        if payload.get(name) is None
    ]
    if missing:
        raise KeyError(f"Boussinesq storage budget requires {', '.join(missing)}")
    stop = first_snapshot + n_periods
    head = np.asarray(payload["head_history_m"], dtype=float)[first_snapshot - 1 : stop]
    volume = (
        np.asarray(payload["cell_area_m2"], dtype=float)
        * np.asarray(payload["storage_coefficient"], dtype=float)
        * np.maximum(head - np.asarray(payload["z_bottom_m"], dtype=float), 0.0)
    )
    elapsed = np.asarray(payload["snapshot_elapsed_seconds"], dtype=float)
    flux = -np.diff(volume, axis=0) / np.diff(elapsed[first_snapshot - 1 : stop]).reshape(-1, 1)
    imposed = payload.get("prescribed_head_history_m_by_cell")
    if imposed is not None and np.size(imposed):
        free = ~np.isfinite(np.asarray(imposed, dtype=float)[first_snapshot:stop])
        flux = flux * free
    return flux


class BoussinesqOutputAdapter:
    """Read Boussinesq state history and inject fields into a Catalog.

    Expects a solver output directory with ``_boussinesq_state_history.npz``
    (head history, derived fluxes) and ``_boussinesq_summary.json``
    (convergence metadata). ``Boussinesq.processing()`` writes both files at
    the end of the solve, mirroring the MODFLOW lifecycle where the run step
    is the only writer of solver outputs.
    """

    solver_name = "boussinesq"
    category = "integrated"

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
        *,
        budget_terms: BudgetKeep = BudgetKeep.everything(),
        start_datetime: object | None = None,
    ) -> None:
        """Read .npz state history and write head and budget fields to the store.

        ``budget_terms`` says which per-cell budget terms are written; the
        lumped budget table always holds every term.
        """
        solver_output_dir = Path(solver_output_dir)
        npz_path = solver_output_dir / "_boussinesq_state_history.npz"

        if not npz_path.exists():
            raise FileNotFoundError(f"No _boussinesq_state_history.npz in {solver_output_dir}")

        with np.load(npz_path) as payload:
            head_history = payload.get("head_history_m")
            if head_history is None:
                head_history = payload.get("final_head_m")
                if head_history is not None:
                    head_history = head_history.reshape(1, -1)

            if head_history is None:
                raise KeyError(f"No head data in {npz_path}")

            if head_history.ndim == 1:
                head_history = head_history.reshape(1, -1)

            # The store stamps each stress period at its end, as the MODFLOW
            # extractors do: the initial state of a transient history closes no
            # period, so it stays in the state group only.
            first = first_period_snapshot(payload, n_snapshots=head_history.shape[0])
            n_timesteps = head_history.shape[0] - first
            n_cells = head_history.shape[1]
            z_top_m = payload.get("z_top_m")
            z_bottom_m = payload.get("z_bottom_m")
            cell_area_m2 = payload.get("cell_area_m2")
            time_values = payload.get("snapshot_elapsed_seconds")
            if time_values is None or len(time_values) < first + n_timesteps:
                raise KeyError(f"No snapshot_elapsed_seconds time axis in {npz_path}")
            # Write /time at period resolution (one entry per head slice). The
            # payload carries relative elapsed seconds, so anchor to the launcher
            # start_datetime for a real calendar axis instead of seconds since 1970.
            writer = getattr(store, "write_time", None)
            if writer is None:
                raise TypeError("Simulation store must implement write_time().")
            values = cf_time_axis_seconds(
                np.asarray(time_values[first : first + n_timesteps], dtype=float),
                start_datetime,
            )
            writer(sim_id, values, epoch=CF_EPOCH, units=CF_TIME_UNITS)

            logger.info(
                "Extracting Boussinesq results: %d timesteps, %d cells",
                n_timesteps,
                n_cells,
            )

            head_stack = np.asarray(
                head_history[first : first + n_timesteps], dtype="float64"
            ).reshape(n_timesteps, 1, n_cells)
            store.write_field_stack(sim_id, "head", head_stack)

            self._persist_state_history(sim_id, store, payload)
            components = self._budget_components(
                payload,
                n_timesteps=n_timesteps,
                n_cells=n_cells,
                cell_area_m2=cell_area_m2,
                first_snapshot=first,
            )
            # The lumped per-component budget holds every term, whatever the
            # per-cell policy: the catchment scalars (discharge, well pumping)
            # are derived from it.
            self._write_budget_table(sim_id, store, components, n_timesteps=n_timesteps)
            self._write_budget_fields(sim_id, store, components, budget_terms=budget_terms)

        self._write_surface_elevation(
            sim_id,
            store,
            solver_output_dir,
            n_cells,
            z_top_m=z_top_m,
            z_bottom_m=z_bottom_m,
        )

    @staticmethod
    def _persist_state_history(sim_id: str, store: Any, payload) -> None:
        """Write all Boussinesq state arrays to a ``boussinesq_state`` Zarr group."""
        sz = store.open_zarr(sim_id)
        try:
            grp = sz.root
            state_grp = grp.require_group("boussinesq_state")
            for key in payload.files:
                arr = np.asarray(payload[key])
                # A restart array shares no axis with its neighbours, so it
                # names its own: an unnamed axis makes the store unopenable.
                state_grp.create_array(
                    key,
                    data=arr,
                    dimension_names=tuple(f"{key}_dim{axis}" for axis in range(arr.ndim)),
                    overwrite=True,
                )
            logger.debug("Persisted %d Boussinesq state arrays to store", len(payload.files))
        finally:
            sz.close()

    @staticmethod
    def _budget_components(
        payload,
        *,
        n_timesteps: int,
        n_cells: int,
        cell_area_m2: np.ndarray | None,
        first_snapshot: int = 0,
    ) -> dict[str, np.ndarray]:
        """Return the per-cell budget stacks with the sign every solver stores.

        Each entry is ``(n_timesteps, n_cells)`` in m3/s, one row per stress
        period from ``first_snapshot`` on, positive when water enters the aquifer
        and negative when it leaves, as MODFLOW signs a budget. The Boussinesq
        residual counts ``drain``, ``surface_excess`` and ``constant_head``
        positive when water leaves, so those three are negated here, once, and
        the state group keeps the solver histories as the solver wrote them.

        ``storage`` is the term of the transient residual, the change of the
        drainable volume over the period: :func:`_storage_flux`. A steady history
        changes no storage and writes no such term.
        """
        area = None if cell_area_m2 is None else np.asarray(cell_area_m2, dtype=float).reshape(-1)
        if area is not None and area.size != int(n_cells):
            raise ValueError(
                f"Boussinesq cell_area_m2 has {area.size} cells; expected {int(n_cells)}"
            )

        def _history(name: str) -> np.ndarray | None:
            values = payload.get(name)
            if values is None:
                return None
            arr = np.asarray(values, dtype=float)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            if arr.shape[1] != int(n_cells):
                raise ValueError(
                    f"Boussinesq array {name!r} has {arr.shape[1]} cells; expected {int(n_cells)}"
                )
            stop = int(first_snapshot) + int(n_timesteps)
            if arr.shape[0] < stop:
                raise ValueError(
                    f"Boussinesq array {name!r} has {arr.shape[0]} timesteps; "
                    f"expected at least {stop}"
                )
            return arr[int(first_snapshot) : stop]

        def _rate_to_flux(name: str, label: str) -> np.ndarray | None:
            rate = _history(name)
            if rate is None:
                return None
            if area is None:
                raise KeyError(f"Boussinesq {label} history requires cell_area_m2")
            return rate * area.reshape(1, -1)

        def _leaving(stack: np.ndarray | None) -> np.ndarray | None:
            return None if stack is None else -stack

        candidates = {
            "recharge": _rate_to_flux("recharge_rate_history_m_s", "recharge"),
            "drain": _leaving(_history("drainage_flux_history_m3_s")),
            "well": _history("well_flux_history_m3_s"),
            "surface_excess": _leaving(
                _rate_to_flux("saturation_excess_history_m_s", "saturation excess")
            ),
            "constant_head": _leaving(_history("prescribed_head_flux_history_m3_s")),
            "storage": _storage_flux(payload, first_snapshot=first_snapshot, n_periods=n_timesteps),
        }
        return {name: stack for name, stack in candidates.items() if stack is not None}

    @staticmethod
    def _write_budget_table(
        sim_id: str,
        store: Any,
        components: dict[str, np.ndarray],
        *,
        n_timesteps: int,
    ) -> None:
        """Write the lumped per-component budget rows (m3/s) for every timestep."""
        records: list[dict[str, Any]] = []
        for name, stack in components.items():
            for t in range(int(n_timesteps)):
                step = stack[t]
                records.append(
                    {
                        "timestep": t,
                        "zone_id": DOMAIN,
                        "component": name,
                        "flux_in": float(np.maximum(step, 0.0).sum()),
                        "flux_out": abs(float(np.minimum(step, 0.0).sum())),
                        "unit": "m3 s-1",
                    }
                )
        if records:
            records.sort(key=lambda record: record["timestep"])
            store.write_budgets(sim_id, records)

    @staticmethod
    def _write_budget_fields(
        sim_id: str,
        store: Any,
        components: dict[str, np.ndarray],
        *,
        budget_terms: BudgetKeep,
    ) -> None:
        """Write the per-cell budget terms the run keeps, with solver units.

        A term has the ``(time, layer, cell)`` shape of every solver, with its one
        layer. ``surface_excess`` is a flux at the land surface and has no layer:
        the seepage mask is rebuilt on read from it. The ``budget/`` group then
        records the policy and the terms kept.
        """
        written: list[str] = []
        for name, stack in components.items():
            if not budget_terms.keeps(name):
                continue
            values = stack if name == "surface_excess" else stack[:, np.newaxis, :]
            store.write_field_stack(sim_id, name, values, subgroup="budget")
            written.append(name)

        sz = store.open_zarr(sim_id)
        try:
            sz.write_budget_policy(budget_terms, written)
        finally:
            sz.close()

    def _write_surface_elevation(
        self,
        sim_id: str,
        store: Any,
        solver_output_dir: Path,
        n_cells: int,
        *,
        z_top_m: np.ndarray | None,
        z_bottom_m: np.ndarray | None,
    ) -> None:
        """Write mesh/topography from the Boussinesq payload or summary."""
        summary: dict[str, Any] = {}
        if z_top_m is None or z_bottom_m is None:
            summary_path = solver_output_dir / "_boussinesq_summary.json"
            if not summary_path.exists():
                raise FileNotFoundError(
                    f"No Boussinesq surface metadata found for sim {sim_id}: {summary_path}"
                )

            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Could not parse Boussinesq summary: {summary_path}") from exc
        raw_z_top = z_top_m if z_top_m is not None else summary.get("z_top_m")
        raw_z_bottom = z_bottom_m if z_bottom_m is not None else summary.get("z_bottom_m")
        if raw_z_top is None or raw_z_bottom is None:
            raise KeyError(
                f"Boussinesq surface metadata missing z_top_m/z_bottom_m for sim {sim_id}"
            )
        z_top = np.asarray(raw_z_top, dtype="float64").reshape(-1)
        z_bottom = np.asarray(raw_z_bottom, dtype="float64").reshape(-1)
        if z_top.size == 1:
            z_top = np.full(n_cells, float(z_top[0]), dtype="float64")
        if z_bottom.size == 1:
            z_bottom = np.full(n_cells, float(z_bottom[0]), dtype="float64")
        if z_top.size != int(n_cells) or z_bottom.size != int(n_cells):
            raise ValueError(
                "Boussinesq surface arrays have incompatible sizes: "
                f"z_top={z_top.size}, z_bottom={z_bottom.size}, n_cells={int(n_cells)}"
            )

        sz = store.open_zarr(sim_id)
        try:
            sz.write_topography(
                topography=z_top,
                z_interfaces=np.vstack([z_top, z_bottom]),
                n_cells=int(n_cells),
                n_layers=1,
                idomain=np.ones((1, int(n_cells)), dtype=np.int8),
                vertical_layout=VERTICAL_LAYOUT_COLUMN_FRACTIONS,
            )
        finally:
            sz.close()
