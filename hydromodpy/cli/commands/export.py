"""``hmp export`` - export geographic or simulation results."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND

NAME: str = "export"
HELP: str = "Export geographic data or simulation results from the project store"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", type=str, help="Path to the project directory")
    parser.add_argument(
        "--list", action="store_true", help="List available rasters, features, and simulations"
    )
    parser.add_argument(
        "--sim", default=None, help="Simulation name to export (use --list to see available)"
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Export timeseries as CSV (default when --sim is used alone)",
    )
    parser.add_argument("--netcdf", action="store_true", help="Export spatial fields as NetCDF")
    parser.add_argument(
        "--geotiff", action="store_true", help="Export spatial fields as GeoTIFF (one per variable)"
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=None,
        help="GeoTIFF pixel size in project CRS units. Required with --geotiff.",
    )
    parser.add_argument("--vtu", action="store_true", help="Export mesh + fields as VTU (ParaView)")
    parser.add_argument(
        "--raster", nargs="+", help="Geographic raster name(s) to export as GeoTIFF"
    )
    parser.add_argument(
        "--feature", nargs="+", help="Geographic feature name(s) to export as shapefile"
    )
    parser.add_argument(
        "--output", default=None, help="Output directory (default: exports/<name>/ in the project)"
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        SimulationCatalog,
        SimulationNotFoundError,
        short_id,
    )

    project_dir = Path(args.project).expanduser().resolve()
    project_name = project_dir.name
    db_path = project_dir / "hydromodpy.duckdb"
    if not db_path.exists():
        print(f"No catalog found at {project_dir}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    catalog = SimulationCatalog(project_dir)
    latest_sid: str | None = None

    if args.list:
        sims = catalog.list_simulations(project=project_name)
        rasters: list[str] = []
        if not sims.empty:
            latest_sid = str(sims.iloc[-1]["sim_id"])
            sz = catalog.open_zarr(latest_sid)
            try:
                geo_grp = sz.root.get("geographic")
                rasters = list(geo_grp.keys()) if geo_grp is not None else []
            finally:
                sz.close()
        features = catalog.list_geographic_features(latest_sid) if latest_sid else []
        print("Geographic rasters:", file=sys.stderr)
        for name in sorted(rasters):
            print(f"  {name}", file=sys.stderr)
        print("\nGeographic features:", file=sys.stderr)
        for name in sorted(features):
            print(f"  {name}", file=sys.stderr)

        if not sims.empty:
            print("\nSimulations:", file=sys.stderr)
            for _, row in sims.iterrows():
                sid = str(row["sim_id"])
                name = row.get("name", "")
                solver = row.get("solver", "")
                status = row.get("status", "")
                created = row.get("created_at", "")
                date_str = str(created)[:16] if created else ""
                label = name or "(no name)"
                print(
                    f"  {label}  [{short_id(sid)}]  solver={solver}  {date_str}  {status}",
                    file=sys.stderr,
                )
        catalog.close()
        return

    output_dir = Path(args.output) if args.output else None
    exported: list[Path] = []

    if args.raster or args.feature:
        geo_dir = output_dir or (project_dir / "exports" / "geographic")
        geo_dir.mkdir(parents=True, exist_ok=True)

        if args.raster:
            sims = catalog.list_simulations(project=project_name)
            if sims.empty:
                print("  No simulations found; cannot export rasters", file=sys.stderr)
            else:
                latest_sid = str(sims.iloc[-1]["sim_id"])
                sz = catalog.open_zarr(latest_sid)
                geo_grp = sz.root.get("geographic")
                for name in args.raster:
                    try:
                        if geo_grp is None or name not in geo_grp:
                            raise KeyError(name)
                        import numpy as np
                        import rasterio
                        from rasterio.transform import Affine

                        data = np.array(geo_grp[name][:])
                        attrs = dict(geo_grp[name].attrs)
                        transform = Affine(*attrs["transform"][:6])
                        crs = attrs.get("crs", "")
                        nodata = attrs.get("nodata", -99999.0)
                        out_path = geo_dir / f"{name}.tif"
                        with rasterio.open(
                            out_path,
                            "w",
                            driver="GTiff",
                            height=data.shape[-2],
                            width=data.shape[-1],
                            count=1,
                            dtype=data.dtype,
                            crs=crs,
                            transform=transform,
                            nodata=nodata,
                        ) as dst:
                            dst.write(data if data.ndim == 3 else data[np.newaxis])
                        exported.append(out_path)
                        print(f"  {out_path}", file=sys.stderr)
                    except KeyError:
                        print(f"  Raster '{name}' not found in store", file=sys.stderr)

        if args.feature:
            for name in args.feature:
                try:
                    gdf = catalog.read_geographic_feature(latest_sid, name)
                    out_path = geo_dir / f"{name}.shp"
                    gdf.to_file(out_path)
                    exported.append(out_path)
                    print(f"  {out_path}", file=sys.stderr)
                except KeyError:
                    print(f"  Feature '{name}' not found in store", file=sys.stderr)

    if args.sim:
        sim_ref = args.sim
        try:
            sim_id = catalog.resolve(sim_ref, project=project_name)
        except AmbiguousReferenceError as exc:
            print(str(exc), file=sys.stderr)
            catalog.close()
            sys.exit(EXIT_NOT_FOUND)
        except SimulationNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            catalog.close()
            sys.exit(EXIT_NOT_FOUND)
        row = catalog.connection.execute(
            "SELECT name FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?",
            [sim_id],
        ).fetchone()
        label = (row[0] if row and row[0] else None) or short_id(sim_id)

        sim_dir = output_dir or (project_dir / "exports" / label)
        sim_dir.mkdir(parents=True, exist_ok=True)

        any_format = args.csv or args.netcdf or args.geotiff or args.vtu
        if not any_format:
            args.csv = True

        if args.csv:
            out = sim_dir / "timeseries.csv"
            catalog.export(sim_id, "*", "csv", out)
            exported.append(out)
            print(f"  {out}", file=sys.stderr)

        if args.netcdf:
            out = sim_dir / "fields.nc"
            try:
                catalog.export(sim_id, "head", "netcdf", out)
                exported.append(out)
                print(f"  {out}", file=sys.stderr)
            except Exception as exc:
                print(f"  NetCDF export failed: {exc}", file=sys.stderr)

        if args.geotiff:
            if args.resolution is None:
                print("--resolution is required with --geotiff", file=sys.stderr)
                catalog.close()
                sys.exit(EXIT_CONFIG)
            failures: list[str] = []
            sz = catalog.open_zarr(sim_id)
            try:
                grp = sz.root
                variables = list(grp.keys()) + list((grp.get("derived") or {}).keys())
            finally:
                sz.close()
            for var in variables:
                if var in (
                    "mesh",
                    "budget",
                    "derived",
                    "pathlines",
                    "forcing",
                    "geographic",
                    "crs",
                    "time",
                ):
                    continue
                try:
                    out = sim_dir / f"{var}_t0.tif"
                    catalog.export(
                        sim_id,
                        var,
                        "geotiff",
                        out,
                        timestep=0,
                        resolution=float(args.resolution),
                    )
                    exported.append(out)
                    print(f"  {out}", file=sys.stderr)
                except Exception as exc:
                    failures.append(f"{var}: {exc}")
            if failures:
                print("GeoTIFF export failed:", file=sys.stderr)
                for failure in failures:
                    print(f"  {failure}", file=sys.stderr)
                catalog.close()
                sys.exit(EXIT_CONFIG)

        if args.vtu:
            out = sim_dir / "head_t0.vtu"
            try:
                catalog.export(sim_id, "head", "vtu", out, timestep=0)
                exported.append(out)
                print(f"  {out}", file=sys.stderr)
            except Exception as exc:
                print(f"  VTU export failed: {exc}", file=sys.stderr)

    catalog.close()
    if not any([args.raster, args.feature, args.sim]):
        print(
            "Usage: hmp export <project> --list | --sim NAME [--csv --netcdf] | --raster NAME",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    if exported:
        print(f"Exported {len(exported)} file(s)", file=sys.stderr)
