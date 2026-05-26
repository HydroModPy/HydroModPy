from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.analysis.testbed.site_selection_catalog import resolve_catalog_source


def _write_manifest(
    directory: Path,
    *,
    outputs: dict[str, str],
    output_root: str | None = ".",
) -> Path:
    manifest_path = directory / "site_selection_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "site_selection_manifest_v1",
                "selection_id": "demo_selection",
                "output_root": output_root,
                "outputs": outputs,
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path


def test_resolve_catalog_source_accepts_direct_path(tmp_path: Path) -> None:
    catalog_path = tmp_path / "regional_lab_sites.csv"
    catalog_path.write_text("site_id,enabled\nsite_01,true\n", encoding="utf-8")

    source = resolve_catalog_source(
        base_dir=tmp_path,
        mapping={"path": "regional_lab_sites.csv"},
        catalog_label="testbed.catalog",
    )

    assert source.path == catalog_path.resolve()
    assert source.source_manifest_path is None
    assert source.source_manifest_output_key is None


def test_resolve_catalog_source_uses_manifest_default_output(tmp_path: Path) -> None:
    selection_dir = tmp_path / "site_selection"
    selection_dir.mkdir()
    catalog_path = selection_dir / "regional_lab_sites.csv"
    catalog_path.write_text("site_id,enabled\nsite_01,true\n", encoding="utf-8")
    manifest_path = _write_manifest(
        selection_dir,
        outputs={"regional_lab_sites_csv": "regional_lab_sites.csv"},
    )

    source = resolve_catalog_source(
        base_dir=tmp_path,
        mapping={
            "from_site_selection_manifest": "site_selection/site_selection_manifest.json",
        },
        catalog_label="testbed.catalog",
    )

    assert source.path == catalog_path.resolve()
    assert source.source_manifest_path == manifest_path.resolve()
    assert source.source_manifest_output_key == "regional_lab_sites_csv"


@pytest.mark.parametrize(
    "alias",
    ["output", "site_selection_output", "site_selection_output_key"],
)
def test_resolve_catalog_source_accepts_output_aliases(
    tmp_path: Path,
    alias: str,
) -> None:
    custom_catalog_path = tmp_path / "selected_sites.csv"
    custom_catalog_path.write_text("site_id,enabled\nsite_01,true\n", encoding="utf-8")
    (tmp_path / "regional_lab_sites.csv").write_text(
        "site_id,enabled\nsite_02,true\n",
        encoding="utf-8",
    )
    manifest_path = _write_manifest(
        tmp_path,
        outputs={
            "regional_lab_sites_csv": "regional_lab_sites.csv",
            "selected_sites_csv": "selected_sites.csv",
        },
    )

    source = resolve_catalog_source(
        base_dir=tmp_path,
        mapping={
            "from_site_selection_manifest": "site_selection_manifest.json",
            alias: "selected_sites_csv",
        },
        catalog_label="regional_lab.catalog",
    )

    assert source.path == custom_catalog_path.resolve()
    assert source.source_manifest_path == manifest_path.resolve()
    assert source.source_manifest_output_key == "selected_sites_csv"


def test_resolve_catalog_source_rejects_path_and_manifest_together(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        resolve_catalog_source(
            base_dir=tmp_path,
            mapping={
                "path": "regional_lab_sites.csv",
                "from_site_selection_manifest": "site_selection_manifest.json",
            },
            catalog_label="testbed.catalog",
        )


def test_resolve_catalog_source_requires_requested_manifest_output(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        outputs={"selected_sites_csv": "selected_sites.csv"},
    )

    with pytest.raises(ValueError, match="does not contain output 'regional_lab_sites_csv'"):
        resolve_catalog_source(
            base_dir=tmp_path,
            mapping={"from_site_selection_manifest": "site_selection_manifest.json"},
            catalog_label="testbed.catalog",
        )


def test_resolve_catalog_source_requires_resolved_output_file(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        outputs={"regional_lab_sites_csv": "missing.csv"},
    )

    with pytest.raises(FileNotFoundError, match="resolved output 'regional_lab_sites_csv'"):
        resolve_catalog_source(
            base_dir=tmp_path,
            mapping={"from_site_selection_manifest": "site_selection_manifest.json"},
            catalog_label="regional_lab.catalog",
        )


def test_resolve_catalog_source_requires_direct_path_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="testbed.catalog.path cannot be empty"):
        resolve_catalog_source(
            base_dir=tmp_path,
            mapping={},
            catalog_label="testbed.catalog",
        )
