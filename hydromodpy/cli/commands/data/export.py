"""``hmp data export`` - export geographic or simulation results."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND
from hydromodpy.core.config_kit.export_spec import ExportSpec
from hydromodpy.core.state.paths import catalog_path_for, share_dir_for

NAME: str = "export"
HELP: str = "Export geographic data or simulation results from the project store"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument("project", type=str, help="Path to the project directory")
    parser.add_argument(
        "--list",
        action="store_true",
        help=(
            "List the fields, rasters and features one run exposes, plus every "
            "simulation in the project. The run read is --sim when given, else "
            "the last live one."
        ),
    )
    parser.add_argument(
        "--sim",
        default=None,
        help=(
            "Simulation name to export, or to read from with --list (use --list to see available)"
        ),
    )
    parser.add_argument(
        "--var",
        nargs="+",
        default=None,
        help=(
            "Field variable name(s) to export (default: all exportable fields "
            "present). List them with --list."
        ),
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
        help="GeoTIFF pixel size in project CRS units. Auto-derived from the grid when omitted.",
    )
    parser.add_argument("--vtu", action="store_true", help="Export mesh + fields as VTU (ParaView)")
    parser.add_argument(
        "--raster", nargs="+", help="Geographic raster name(s) to export as GeoTIFF"
    )
    parser.add_argument(
        "--feature", nargs="+", help="Geographic feature name(s) to export as shapefile"
    )
    parser.add_argument(
        "--format",
        dest="fair_format",
        choices=("hmp", "stac", "rocrate", "prov"),
        action="append",
        default=None,
        help=(
            "Also emit, alongside the per-variable exports: 'hmp' a portable "
            ".hmp archive (same as `hmp catalog export`), or a 'stac'/'rocrate'/"
            "'prov' metadata sidecar. Repeatable to render several."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: share/<name>/ in the project)",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog import (
        AmbiguousReferenceError,
        Catalog,
        SimulationNotFoundError,
        short_id,
    )

    project_dir = Path(args.project).expanduser().resolve()
    project_name = project_dir.name
    db_path = catalog_path_for(project_dir)
    if not db_path.exists():
        print(f"No catalog found at {project_dir}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    catalog = Catalog(project_dir)

    if args.list:
        sims = catalog.list_simulations(project=project_name)
        # Fields, rasters and features are read from one run, so pick it
        # explicitly: --sim when given, else the last live run. A trashed run
        # is still listed below but must not silently become the source.
        list_sid: str | None = None
        list_label = ""
        if args.sim:
            try:
                list_sid = catalog.resolve(args.sim, project=project_name)
            except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
                print(str(exc), file=sys.stderr)
                catalog.close()
                sys.exit(EXIT_NOT_FOUND)
            list_label = args.sim
        elif not sims.empty:
            live = sims[sims["status"] != "trashed"] if "status" in sims else sims
            row = (live if not live.empty else sims).iloc[-1]
            list_sid = str(row["sim_id"])
            list_label = str(row["name"] or short_id(list_sid))

        fields: list[str] = []
        rasters: list[str] = []
        if list_sid is not None:
            sz = catalog.open_zarr(list_sid)
            try:
                geo_grp = sz.root.get("geographic")
                rasters = list(geo_grp.keys()) if geo_grp is not None else []
            finally:
                sz.close()
            fields = _exportable_fields(catalog, list_sid)
        features = catalog.list_geographic_features(list_sid) if list_sid else []

        source = f" ({list_label})" if list_label else ""
        print(f"Simulation fields{source}:", file=sys.stderr)
        for name in fields:
            print(f"  {name}", file=sys.stderr)
        print(f"\nGeographic rasters{source}:", file=sys.stderr)
        for name in sorted(rasters):
            print(f"  {name}", file=sys.stderr)
        print(f"\nGeographic features{source}:", file=sys.stderr)
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
        geo_dir = output_dir or (share_dir_for(project_dir) / "geographic")
        geo_dir.mkdir(parents=True, exist_ok=True)

        # Honor --sim for geographic exports; fall back to the latest run.
        geo_sid: str | None = None
        if args.sim:
            try:
                geo_sid = catalog.resolve(args.sim, project=project_name)
            except (AmbiguousReferenceError, SimulationNotFoundError) as exc:
                print(str(exc), file=sys.stderr)
                catalog.close()
                sys.exit(EXIT_NOT_FOUND)
        else:
            sims = catalog.list_simulations(project=project_name)
            if not sims.empty:
                geo_sid = str(sims.iloc[-1]["sim_id"])

        if geo_sid is None:
            print("  No simulations found; cannot export geographic data", file=sys.stderr)
        else:
            if args.raster:
                sz = catalog.open_zarr(geo_sid)
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
                        gdf = catalog.read_geographic_feature(geo_sid, name)
                        out_path = geo_dir / f"{name}.gpkg"
                        gdf.to_file(out_path, driver="GPKG")
                        exported.append(out_path)
                        print(f"  {out_path}", file=sys.stderr)
                    except KeyError:
                        print(f"  Feature '{name}' not found in store", file=sys.stderr)

    fair_formats: tuple[str, ...] = tuple(args.fair_format or ())

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

        sim_dir = output_dir or (share_dir_for(project_dir) / label)
        sim_dir.mkdir(parents=True, exist_ok=True)

        any_format = args.csv or args.netcdf or args.geotiff or args.vtu
        if not any_format:
            args.csv = True

        if args.geotiff and args.resolution is None:
            print("--resolution is required with --geotiff", file=sys.stderr)
            catalog.close()
            sys.exit(EXIT_CONFIG)

        # Real, registered field names present in this run (whitelist via the
        # field registry: skips Zarr groups like 'geographic', 'mesh', 'crs').
        field_vars: list[str] = []
        if args.netcdf or args.geotiff or args.vtu:
            field_vars = _exportable_fields(catalog, sim_id, args.var)
            if args.var:
                for name in (v for v in args.var if v not in field_vars):
                    print(f"  Variable '{name}' is not an exportable field", file=sys.stderr)

        if args.csv:
            out = sim_dir / "timeseries.csv"
            catalog.export(sim_id, ExportSpec(var="*", dest=out))
            exported.append(out)
            print(f"  {out}", file=sys.stderr)

        if args.netcdf:
            out = sim_dir / "fields.nc"
            try:
                catalog.export(sim_id, ExportSpec(var=field_vars or ["head"], dest=out, time="all"))
                exported.append(out)
                print(f"  {out}", file=sys.stderr)
            except Exception as exc:
                print(f"  NetCDF export failed: {exc}", file=sys.stderr)

        if args.geotiff:
            failures: list[str] = []
            for var in field_vars:
                try:
                    out = sim_dir / f"{var}_t0.tif"
                    catalog.export(
                        sim_id,
                        ExportSpec(var=var, dest=out, time="first", resolution=args.resolution),
                    )
                    exported.append(out)
                    print(f"  {out}", file=sys.stderr)
                except Exception as exc:
                    failures.append(f"{var}: {exc}")
            if failures:
                print("GeoTIFF export failed for some variables:", file=sys.stderr)
                for failure in failures:
                    print(f"  {failure}", file=sys.stderr)

        if args.vtu:
            vtu_failures: list[str] = []
            for var in field_vars:
                try:
                    out = sim_dir / f"{var}_t0.vtu"
                    catalog.export(sim_id, ExportSpec(var=var, dest=out, time="first"))
                    exported.append(out)
                    print(f"  {out}", file=sys.stderr)
                except Exception as exc:
                    vtu_failures.append(f"{var}: {exc}")
            if vtu_failures:
                print("VTU export failed for some variables:", file=sys.stderr)
                for failure in vtu_failures:
                    print(f"  {failure}", file=sys.stderr)

        if fair_formats:
            exported.extend(_emit_fair(catalog, sim_id, sim_dir, fair_formats))

    catalog.close()
    if not any([args.raster, args.feature, args.sim, exported]):
        print(
            "Usage: hmp data export <project> --list [--sim NAME] | "
            "--sim NAME [--csv --netcdf] | --raster NAME",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    if exported:
        print(f"Exported {len(exported)} file(s)", file=sys.stderr)


def _exportable_fields(catalog, sim_id: str, selected: list[str] | None = None) -> list[str]:
    """Registered field names a run can export, persisted or rebuilt on read.

    Delegates to ``run.array.list_fields()``, the single source of truth for
    what a store exposes: registry names found at the root or in the ``state``,
    ``derived``, ``budget`` and ``mesh`` subgroups, plus the virtual fields it
    can rebuild (water-table elevation/depth, seepage mask, drain outflow). A
    default run persists only the head, yet those are readable, so they must be
    exportable too. Reading that list here rather than rebuilding it is what
    keeps a per-cell budget field such as ``drain`` from being readable through
    the API and refused by the CLI.
    When ``selected`` is given, keep only those requested names that exist.
    """
    fields = catalog[sim_id].array.list_fields()
    if selected:
        return [v for v in selected if v in fields]
    return fields


def _emit_fair(
    catalog,
    sim_id: str,
    sim_dir: Path,
    formats: tuple[str, ...],
) -> list[Path]:
    """Render the FAIR sidecars selected via ``--format``."""
    from hydromodpy.results.export import (
        build_context,
        write_ro_crate,
        write_stac_item,
    )
    from hydromodpy.results.export.prov import write_prov

    context = build_context(catalog, sim_id)
    out_paths: list[Path] = []
    for fmt in formats:
        try:
            if fmt == "hmp":
                # Real portable archive (config, provenance, fields, timeseries),
                # not just a metadata sidecar. Same output as `hmp catalog export`.
                archive = sim_dir / f"{sim_dir.name}.hmp"
                path = catalog.export_package(sim_id, archive)
                catalog.record_export(sim_id, kind="hmp", path=path)
            elif fmt == "rocrate":
                path = write_ro_crate(catalog, sim_id, sim_dir, context=context)
            elif fmt == "stac":
                path = write_stac_item(catalog, sim_id, sim_dir, context=context)
            elif fmt == "prov":
                path = write_prov(catalog, sim_id, sim_dir, context=context)
            else:
                continue
        except Exception as exc:  # noqa: BLE001 - surfaced to CLI
            print(f"  FAIR export ({fmt}) failed: {exc}", file=sys.stderr)
            continue
        out_paths.append(path)
        print(f"  {path}", file=sys.stderr)
    return out_paths
