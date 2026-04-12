from __future__ import annotations

import csv
from pathlib import Path


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


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    pilot_dir = Path(__file__).resolve().parent
    repo_root = pilot_dir.parents[1]
    catalog_path = pilot_dir / "site_catalog_pilot_20.csv"
    child_dir = pilot_dir / "child_configs"
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

    generated_count = 0
    for row in rows:
        site_id = str(row.get("site_id", "")).strip()
        cluster_id = str(row.get("cluster_id", "")).strip()
        mesh_path = str(row.get("mesh_output_mesh", "")).strip()
        bundle_dir = str(row.get("mesh_bundle_dir", "")).strip()
        x_value = str(row.get("x", "")).strip()
        y_value = str(row.get("y", "")).strip()

        should_generate = site_id == "headwater_100km2_outlet_27" or cluster_id == "s3_10km2"
        if not should_generate or mesh_path == "" or bundle_dir == "" or x_value == "" or y_value == "":
            continue

        config_path = child_dir / f"run_{site_id}_boussinesq_local_mesh_replay.toml"
        _write_text(
            config_path,
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
                    f'bundle_dir = "{Path(bundle_dir).resolve().as_posix()}"',
                    "",
                    "[simulation]",
                    f'name = "{site_id} local boussinesq mesh replay"',
                    f'run_id = "{site_id}_local_boussinesq_mesh_replay"',
                ]
            )
            + "\n",
        )

        row["simulation_reference_config"] = str(config_path.relative_to(pilot_dir).as_posix())
        row["tags"] = _merge_tags(row.get("tags", ""), "simulation_ready")
        existing_note = str(row.get("notes", "")).strip()
        note = "generated local boussinesq mesh replay config"
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
    print(f"Updated catalog: {catalog_path}")


if __name__ == "__main__":
    main()
