"""Full-Python equivalent of run_transient_nwt.toml.

Reproduces the Nancon transient MODFLOW-NWT configuration without a TOML
file, using factory methods on the public config classes.
"""

from __future__ import annotations

from pathlib import Path

import hydromodpy as hmp
from hydromodpy.core.workspace.config import WorkspaceConfig

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "data"


def build_config() -> hmp.Config:
    return hmp.Config(
        workflow="simulation",
        workspace=WorkspaceConfig(project_root=HERE),
        geographic=hmp.Geographic.from_outlet(
            x=389285.91,
            y=6816518.749,
            dem=DATA / "dem" / "DEM_armorican_massif.tif",
            snap_dist="150 m",
            buff_area="10%",
            crs_project="EPSG:2154",
        ),
        domain=hmp.Domain.with_thickness(30.0),
        data=hmp.Data(
            types=["dem", "geology", "hydrography", "hydrometry", "recharge"],
            dem=hmp.DEM.from_geotiff(DATA / "dem" / "DEM_armorican_massif.tif"),
            geology=hmp.Geology.brgm_1m(),
            hydrometry=hmp.Hydrometry.from_csv_directory(
                DATA / "hydrometry",
                start="2000-01-01",
                end="2002-12-31",
            ),
            recharge=hmp.Recharge.from_csv_directory(
                DATA / "recharge",
                start="2000-01-01",
                end="2002-12-31",
            ),
        ),
        flow=hmp.Flow.homogeneous(
            K=5e-5,
            Sy=0.05,
            Ss=1e-5,
            active_bc=["drainage"],
            active_sinks_sources=["recharge"],
        ),
        simulation=hmp.Sim.transient(
            time=("2000-01-01", "2002-12-31", "1 month"),
            flow="modflownwt",
            name="nancon_transient_nwt",
        ),
    )


def main() -> None:
    cfg = build_config()
    with hmp.Project(cfg) as project:
        run = project.run()
        print(f"sim_id={run.sim_id} name={run.name}")


if __name__ == "__main__":
    main()
