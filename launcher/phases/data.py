"""Phase 'data': load climatic and oceanic data.

Hydrography, Intermittency and Hydrometry are intentionally left to hooks
because their constructors require study-specific arguments (file names,
field names, …) that cannot be expressed generically in config.toml.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from launcher.run_result import RunResult


def _run_data(result: "RunResult") -> None:
    from hydromodpy.watershed.climatic import Climatic
    from hydromodpy.data_managers.oceanic import Oceanic

    ws = result.workspace

    # ── Climatic ─────────────────────────────────────────────────────────────
    result.climatic = Climatic(out_path=ws.catch_folder)

    # ── Oceanic ──────────────────────────────────────────────────────────────
    oceanic = Oceanic()
    oceanic.extract_local_data(
        out_path=ws.catch_folder,
        geographic=result.geographic,
        oceanic_path=result.cfg.workspace.data_path,
    )
    try:
        oceanic.download_SHOM_data(
            geographic=result.geographic,
            start_date="2003-01-01",
            end_date="2003-01-30",
        )
        oceanic.update_MSL(oceanic.SHOM_data["value"].mean())
    except Exception as exc:
        print(f"SHOM download failed ({exc}), using default MSL=0.0")
        oceanic.update_MSL(0.0)

    result.oceanic = oceanic

    # Inject MSL into ocean boundary condition
    if "ocean" in result.flow.boundary_conditions:
        result.flow.boundary_conditions["ocean"].value = oceanic.MSL
