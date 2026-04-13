from __future__ import annotations

import csv
from pathlib import Path
import shutil
import sys


PILOT_DIR = Path(__file__).resolve().parent
REPO_ROOT = PILOT_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from launchers.regional_lab.bootstrap import inspect_mesh_bundle_boussinesq_readiness


def _merge_tags(raw_tags: str, *extra_tags: str) -> str:
    items = [item.strip() for item in str(raw_tags).split(";") if item.strip()]
    seen = {item.lower() for item in items}
    for tag in extra_tags:
        normalized = tag.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        items.append(tag)
    return ";".join(items)


def _remove_tag(raw_tags: str, tag_to_remove: str) -> str:
    lowered = str(tag_to_remove).strip().lower()
    items = [
        item.strip()
        for item in str(raw_tags).split(";")
        if item.strip() and item.strip().lower() != lowered
    ]
    return ";".join(items)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _ensure_field(fieldnames: list[str], name: str) -> None:
    if name not in fieldnames:
        fieldnames.append(name)


def _prepare_sanitized_bundle_from_means(
    *,
    site_id: str,
    bundle_dir: str,
    sanitized_root: Path,
) -> tuple[Path, dict[str, int]] | None:
    source_dir = Path(bundle_dir).resolve()
    cells_path = source_dir / "cells.csv"
    if not cells_path.is_file():
        return None

    with cells_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    top_fixes = 0
    bottom_fixes = 0
    for row in rows:
        if (
            str(row.get("z_top_centroid", "")).strip() == ""
            and str(row.get("z_top_mean", "")).strip() != ""
        ):
            row["z_top_centroid"] = str(row.get("z_top_mean", "")).strip()
            top_fixes += 1
        if (
            str(row.get("z_bottom_centroid", "")).strip() == ""
            and str(row.get("z_bottom_mean", "")).strip() != ""
        ):
            row["z_bottom_centroid"] = str(row.get("z_bottom_mean", "")).strip()
            bottom_fixes += 1

    if top_fixes == 0 and bottom_fixes == 0:
        return None

    target_dir = sanitized_root / f"{site_id}_bundle"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)

    with (target_dir / "cells.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    (target_dir / "regional_lab_sanitization.txt").write_text(
        "\n".join(
            [
                f"site_id = {site_id}",
                f"source_bundle_dir = {source_dir}",
                f"filled_z_top_centroid_from_mean = {top_fixes}",
                f"filled_z_bottom_centroid_from_mean = {bottom_fixes}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return target_dir, {
        "filled_z_top_centroid_from_mean": top_fixes,
        "filled_z_bottom_centroid_from_mean": bottom_fixes,
    }


def _describe_not_ready(row: dict[str, str]) -> str:
    details: list[str] = []
    missing_top = str(row.get("bundle_missing_top_centroid_count", "")).strip()
    missing_bottom = str(row.get("bundle_missing_bottom_centroid_count", "")).strip()
    missing_k = str(row.get("bundle_missing_hydraulic_conductivity_count", "")).strip()
    invalid_vertical = str(row.get("bundle_invalid_vertical_geometry_count", "")).strip()
    if missing_top not in ("", "0"):
        details.append(f"missing_top_centroid={missing_top}")
    if missing_bottom not in ("", "0"):
        details.append(f"missing_bottom_centroid={missing_bottom}")
    if missing_k not in ("", "0"):
        details.append(f"missing_hydraulic_conductivity={missing_k}")
    if invalid_vertical not in ("", "0"):
        details.append(f"invalid_vertical_geometry={invalid_vertical}")
    if not details:
        details.append("bundle validation unavailable")
    return "local replay withheld: " + ", ".join(details)


def main() -> None:
    pilot_dir = PILOT_DIR
    repo_root = REPO_ROOT
    catalog_path = pilot_dir / "site_catalog_pilot_20.csv"
    child_dir = pilot_dir / "child_configs"
    sanitized_root = pilot_dir / "sanitized_bundles"
    common_base_path = child_dir / "base_local_boussinesq_mesh_replay.toml"
    dem_path = (repo_root / "examples" / "data" / "dem" / "DEM_armorican_massif.tif").resolve()
    example_base_config = (
        repo_root
        / "examples"
        / "projects"
        / "launcher_simulation"
        / "run_headwater_100km2_outlet_2_boussinesq_mesh_input.toml"
    ).resolve()

    _write_text(
        common_base_path,
        "\n".join(
            [
                "# Shared local replay base for machine-local mesh bundles.",
                f'base_config = "{example_base_config.as_posix()}"',
                "",
                "[geographic]",
                f'dem_init_path = "{dem_path.as_posix()}"',
                "",
                "[flow]",
                "runtime_max_iterations = 200",
                "",
                "[postprocess]",
                "enabled = false",
                "",
                "[display]",
                "enabled = false",
                "show = false",
                "save = false",
            ]
        )
        + "\n",
    )

    with catalog_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for field_name in (
        "bundle_cell_count",
        "bundle_missing_top_centroid_count",
        "bundle_missing_bottom_centroid_count",
        "bundle_missing_hydraulic_conductivity_count",
        "bundle_missing_storage_coefficient_count",
        "bundle_invalid_vertical_geometry_count",
        "bundle_storage_default_value",
        "bundle_boussinesq_steady_ready",
        "bundle_boussinesq_transient_ready",
        "local_simulation_reference_config",
    ):
        _ensure_field(fieldnames, field_name)

    child_dir.mkdir(parents=True, exist_ok=True)
    sanitized_root.mkdir(parents=True, exist_ok=True)
    for stale_path in child_dir.glob("run_*_boussinesq_local_mesh_replay.toml"):
        stale_path.unlink()

    generated_count = 0
    withheld_count = 0
    for row in rows:
        site_id = str(row.get("site_id", "")).strip()
        cluster_id = str(row.get("cluster_id", "")).strip()
        mesh_path = str(row.get("mesh_output_mesh", "")).strip()
        bundle_dir = str(row.get("mesh_bundle_dir", "")).strip()
        x_value = str(row.get("x", "")).strip()
        y_value = str(row.get("y", "")).strip()

        should_generate = site_id == "headwater_100km2_outlet_27" or cluster_id == "s3_10km2"
        if not should_generate:
            continue

        effective_bundle_dir = bundle_dir
        readiness = inspect_mesh_bundle_boussinesq_readiness(bundle_dir or None)
        repair_note = ""
        if str(readiness.get("bundle_boussinesq_steady_ready", "")).strip().lower() != "true":
            repaired = _prepare_sanitized_bundle_from_means(
                site_id=site_id,
                bundle_dir=bundle_dir,
                sanitized_root=sanitized_root,
            )
            if repaired is not None:
                repaired_bundle_dir, repair_counts = repaired
                repaired_readiness = inspect_mesh_bundle_boussinesq_readiness(
                    repaired_bundle_dir
                )
                if (
                    str(repaired_readiness.get("bundle_boussinesq_steady_ready", ""))
                    .strip()
                    .lower()
                    == "true"
                ):
                    effective_bundle_dir = str(repaired_bundle_dir.resolve())
                    readiness = repaired_readiness
                    repair_note = (
                        "sanitized bundle with centroid fallback from mean values "
                        f"(top={repair_counts['filled_z_top_centroid_from_mean']}, "
                        f"bottom={repair_counts['filled_z_bottom_centroid_from_mean']})"
                    )
        for key, value in readiness.items():
            row[key] = "" if value is None else str(value)
        steady_ready = str(row.get("bundle_boussinesq_steady_ready", "")).strip().lower() == "true"
        generated_config_path = child_dir / f"run_{site_id}_boussinesq_local_mesh_replay.toml"
        generated_config_relpath = str(generated_config_path.relative_to(pilot_dir).as_posix())
        config_field_name = (
            "local_simulation_reference_config"
            if site_id == "headwater_100km2_outlet_27"
            else "simulation_reference_config"
        )
        current_simulation_config = str(row.get(config_field_name, "")).strip()

        if (
            not steady_ready
            or mesh_path == ""
            or effective_bundle_dir == ""
            or x_value == ""
            or y_value == ""
        ):
            if current_simulation_config == generated_config_relpath:
                row[config_field_name] = ""
            row["tags"] = _remove_tag(row.get("tags", ""), "simulation_ready")
            existing_note = str(row.get("notes", "")).strip()
            withheld_note = _describe_not_ready(row)
            if withheld_note not in existing_note:
                row["notes"] = (
                    withheld_note
                    if existing_note == ""
                    else f"{existing_note}; {withheld_note}"
                )
            withheld_count += 1
            continue

        _write_text(
            generated_config_path,
            "\n".join(
                [
                    f'base_config = "{common_base_path.resolve().as_posix()}"',
                    "",
                    "[workspace]",
                    f'project_root = "{(pilot_dir / "outputs" / "child_runs" / site_id).resolve().as_posix()}"',
                    "",
                    "[geographic]",
                    f"x_outlet = {x_value}",
                    f"y_outlet = {y_value}",
                    "",
                    "[mesh_input]",
                    f'mesh_path = "{Path(mesh_path).resolve().as_posix()}"',
                    f'bundle_dir = "{Path(effective_bundle_dir).resolve().as_posix()}"',
                    "",
                    "[simulation]",
                    f'name = "{site_id} local boussinesq mesh replay"',
                    f'run_id = "{site_id}_local_boussinesq_mesh_replay"',
                ]
            )
            + "\n",
        )

        row[config_field_name] = generated_config_relpath
        row["tags"] = _merge_tags(row.get("tags", ""), "simulation_ready")
        existing_note = str(row.get("notes", "")).strip()
        note = "generated local boussinesq mesh replay config (steady-ready bundle)"
        if repair_note != "":
            row["tags"] = _merge_tags(row.get("tags", ""), "bundle_sanitized_from_mean")
            note = f"{note}; {repair_note}"
        if existing_note == "":
            row["notes"] = note
        elif note not in existing_note:
            row["notes"] = f"{existing_note}; {note}"
        generated_count += 1

    with catalog_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"Generated local replay configs: {generated_count}")
    print(f"Withheld local replay configs: {withheld_count}")
    print(f"Updated catalog: {catalog_path}")


if __name__ == "__main__":
    main()
