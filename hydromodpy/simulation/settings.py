"""Runtime flow pre-processing settings used by the launcher workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Settings:
    """Mutable settings consumed by flow adapters during preprocessing.

    This object intentionally stores only the options still used by the modern
    process-simulation runtime.
    """

    # Kept for backward compatibility with legacy scripts.
    model_name: str = "default"
    box: bool = True
    sink_fill: bool = False
    check_grid: bool = True
    sim_state: str = "transient"
    dis_perlen: bool = False
    bc_left: float | str | None = None
    bc_right: float | str | None = None
    zone_partic: str | None = None
    depth_init: float = 0.0
    well_coords: list[Any] = field(default_factory=list)
    well_rates: list[float] = field(default_factory=list)
    lay_well: int | None = None

    def update_model_name(self, model_name: str) -> None:
        self.model_name = model_name

    def update_box_model(self, box: bool) -> None:
        self.box = bool(box)

    def update_sink_fill(self, sink_fill: bool) -> None:
        self.sink_fill = bool(sink_fill)

    def update_simulation_state(self, sim_state: str) -> None:
        self.sim_state = sim_state

    def update_check_model(
        self,
        check_grid: bool | None = None,
    ) -> None:
        if check_grid is not None:
            self.check_grid = bool(check_grid)

    def update_dis_perlen(self, dis_perlen: bool) -> None:
        self.dis_perlen = bool(dis_perlen)

    def update_bc_sides(self, bc_left: float | str | None, bc_right: float | str | None) -> None:
        self.bc_left = bc_left
        self.bc_right = bc_right

    def update_well_pumping(
        self,
        well_coords: list[Any] | None = None,
        well_rates: list[float] | None = None,
        lay_well: int | None = None,
    ) -> None:
        self.well_coords = [] if well_coords is None else list(well_coords)
        self.well_rates = [] if well_rates is None else list(well_rates)
        self.lay_well = lay_well

    def update_input_particles(self, zone_partic: str, depth_init: float = 0.0) -> None:
        self.zone_partic = zone_partic
        self.depth_init = float(depth_init)
