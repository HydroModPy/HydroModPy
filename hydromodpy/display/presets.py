"""Shipped presets: named figure requests whose panels list the holes a user fills.

A user writes more in ``[display.presets.<name>]`` with the same fields. A special
figure is a preset whose request carries ``special``, so a TOML file names it without
naming code. The name of a special is the name of its module in ``display/special`` and
the key of its row in ``request.SPECIALS``. This module imports no special, so a
configuration that names a preset stays light.
"""

from __future__ import annotations

from hydromodpy.display.request import SPECIALS, FigureRequest, PanelRequest, named

CATCHMENT = "zone:catchment"

PANEL_PRESETS: dict[str, FigureRequest] = {
    "hydrograph": FigureRequest(
        panels=[
            PanelRequest(type="series", variable="recharge", station=CATCHMENT, holes=["time"]),
            PanelRequest(
                type="series",
                variable="discharge",
                observed=True,
                scores=True,
                scale="linear",
                holes=["variable", "station", "scale", "time"],
            ),
        ]
    ),
    "residuals": FigureRequest(
        panels=[
            PanelRequest(
                type="series",
                variable="discharge",
                against="observed",
                reference=["zero"],
                scores=True,
                holes=["variable", "station"],
            ),
            PanelRequest(
                type="distribution",
                variable="discharge",
                against="observed",
                holes=["variable", "station"],
            ),
        ]
    ),
    "water_budget": FigureRequest(
        panels=[
            PanelRequest(
                type="series",
                variable="budget",
                station=CATCHMENT,
                stack=True,
                holes=["variable", "station", "time"],
            ),
            PanelRequest(
                type="groups",
                variable="budget",
                station=CATCHMENT,
                reduce="mean",
                holes=["variable", "station", "time"],
            ),
        ]
    ),
    "watershed_id_card": FigureRequest(
        panels=[
            PanelRequest(
                variable="topography",
                overlays=["relief", "outline", "outlet", "network", "stations", "scale_bar"],
            ),
            PanelRequest(
                type="table",
                variable=[
                    "simulation.solver",
                    "simulation.flow_regime",
                    "simulation.period_start",
                    "simulation.period_end",
                    "simulation.n_timesteps",
                    "simulation.n_cells",
                    "simulation.n_layers",
                ],
            ),
        ]
    ),
    "network_expansion": FigureRequest(
        panels=[
            PanelRequest(
                type="series",
                variable="simulated_active_network",
                station=CATCHMENT,
                holes=["time"],
            ),
            PanelRequest(
                type="series", variable="discharge", observed=True, holes=["station", "time"]
            ),
        ]
    ),
}

SPECIAL_PRESETS: dict[str, FigureRequest] = {
    name: FigureRequest(special=name, width=row.width) for name, row in SPECIALS.items()
}

PRESETS: dict[str, FigureRequest] = named({**PANEL_PRESETS, **SPECIAL_PRESETS})
"""Every shipped preset. The key of a preset is its name, written once."""
