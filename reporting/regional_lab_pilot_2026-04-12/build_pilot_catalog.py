from __future__ import annotations

import csv
from pathlib import Path


HEADWATER_SITE_IDS = (
    "headwater_100km2_outlet_2",
    "headwater_100km2_outlet_3",
    "headwater_100km2_outlet_4",
    "headwater_100km2_outlet_5",
    "headwater_100km2_outlet_6",
    "headwater_100km2_outlet_7",
    "headwater_100km2_outlet_8",
    "headwater_100km2_outlet_9",
    "headwater_100km2_outlet_10",
    "headwater_100km2_outlet_27",
)

S3_SITE_IDS = (
    "s3_10km2_outlet_2",
    "s3_10km2_outlet_6",
    "s3_10km2_outlet_7",
    "s3_10km2_outlet_8",
    "s3_10km2_outlet_9",
    "s3_10km2_outlet_10",
    "s3_10km2_outlet_11",
    "s3_10km2_outlet_12",
    "s3_10km2_outlet_13",
    "s3_10km2_outlet_14",
)


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _merge_tags(raw_tags: str, *extra_tags: str) -> str:
    items = [item.strip() for item in str(raw_tags).split(";") if item.strip()]
    seen = {item.lower() for item in items}
    for tag in extra_tags:
        lowered = tag.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        items.append(tag)
    return ";".join(items)


def main() -> None:
    pilot_dir = Path(__file__).resolve().parent
    headwater_rows = _load_rows(pilot_dir / "headwater_100km2_catalog_full.csv")
    s3_rows = _load_rows(pilot_dir / "s3_10km2_catalog_full.csv")

    headwater_by_id = {row["site_id"]: dict(row) for row in headwater_rows}
    s3_by_id = {row["site_id"]: dict(row) for row in s3_rows}
    selected_rows = []
    for site_id in HEADWATER_SITE_IDS:
        if site_id not in headwater_by_id:
            raise KeyError(f"Missing headwater pilot site in full catalog: {site_id}")
        selected_rows.append(dict(headwater_by_id[site_id]))
    for site_id in S3_SITE_IDS:
        if site_id not in s3_by_id:
            raise KeyError(f"Missing s3 pilot site in full catalog: {site_id}")
        row = dict(s3_by_id[site_id])
        if str(row.get("bundle_boussinesq_steady_ready", "")).strip().lower() != "true":
            raise ValueError(f"S3 pilot site is not boussinesq steady-ready: {site_id}")
        selected_rows.append(row)

    fieldnames: list[str] = []
    for row in selected_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    for extra_field in (
        "simulation_reference_config",
        "backend_comparison_config",
        "transient_backend_comparison_config",
    ):
        if extra_field not in fieldnames:
            fieldnames.append(extra_field)

    for row in selected_rows:
        row.setdefault("simulation_reference_config", "")
        row.setdefault("backend_comparison_config", "")
        row.setdefault("transient_backend_comparison_config", "")

        if row["site_id"] == "headwater_100km2_outlet_2":
            row["site_status"] = "ready"
            row["maturity"] = "validated"
            row["tags"] = _merge_tags(
                row.get("tags", ""),
                "simulation_ready",
                "backend_ready",
                "transient_ready",
            )
            row["notes"] = "repo-backed child configs available"
            row["simulation_reference_config"] = (
                "../../examples/projects/launcher_simulation/"
                "run_headwater_100km2_outlet_2_mf6_transient_reference.toml"
            )
            row["backend_comparison_config"] = (
                "../../examples/projects/launcher_simulation/"
                "run_method_comparison_headwater_100km2_outlet_2_backends.toml"
            )
            row["transient_backend_comparison_config"] = (
                "../../examples/projects/launcher_simulation/"
                "run_method_comparison_headwater_100km2_outlet_2_"
                "transient_pulsed_recharge_backends.toml"
            )

    output_path = pilot_dir / "site_catalog_pilot_20.csv"
    _write_rows(output_path, fieldnames, selected_rows)
    print(f"Wrote pilot catalog: {output_path}")
    print(f"Selected headwater sites: {len(HEADWATER_SITE_IDS)}")
    print(f"Selected s3 pilot sites: {len(S3_SITE_IDS)}")


if __name__ == "__main__":
    main()
