"""``hmp report compare`` reads N sealed run directories and writes one comparison page.

Every run here is sealed by ``RunRecord.write`` and carries a ``fields.zarr``
with its mesh and its heads, as a completed run does. The comparison never
opens the project index (``Catalog.__init__`` raises), never writes into a
run, refuses runs that are not one case, and writes its folder under
``summary/report/compare/`` of the project.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr

from hydromodpy.analysis.comparison.runs import ComparisonCaseError, ComparisonReferenceError
from hydromodpy.cli.helpers import EXIT_NOT_FOUND, EXIT_VALIDATION
from hydromodpy.cli.main import main as hmp_main
from hydromodpy.core.field_routing import DOMAIN_BUDGET_ZONE
from hydromodpy.reporting.comparison.compare import (
    compare_runs,
    comparison_name,
    reference_labels,
)
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.manifest import ManifestGeometry, ManifestRun, ManifestSite
from hydromodpy.results.record import RunProvenance
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    RUN_CONFIG_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.zarr_store import SimulationZarr
from tests.unit.results._run_record_factory import (
    ATTEMPT_ID,
    NOW,
    make_identity,
    make_record,
)

NROW, NCOL = 3, 4
N_CELLS = NROW * NCOL
N_STEPS = 3
XMIN, YMAX, STEP = 350000.0, 6800030.0, 10.0
OUTLET = (XMIN + 15.0, YMAX - 15.0)
MESH_HASH = "mesh0001"


def _sim_id(name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"


def _write_fields(run_dir: Path, *, head_offset: float) -> None:
    """A 3 x 4 grid of 10 m cells, row 0 at the north, and three steps of heads."""
    fields = run_dir / FIELDS_STORE_NAME
    store = SimulationZarr.create(fields, n_cells=N_CELLS, n_layers=1)
    heads = (
        100.0 + head_offset + np.arange(N_STEPS * N_CELLS, dtype=float).reshape(N_STEPS, N_CELLS)
    )
    store.write_field_stack("watertable_elevation", heads)
    store.close()
    ys = YMAX - STEP * np.arange(NROW + 1)
    xs = XMIN + STEP * np.arange(NCOL + 1)
    vertices = np.array([[x, y, 0.0] for y in ys for x in xs])
    node = np.arange((NROW + 1) * (NCOL + 1)).reshape(NROW + 1, NCOL + 1)
    faces = np.array(
        [
            [node[i, j], node[i, j + 1], node[i + 1, j + 1], node[i + 1, j]]
            for i in range(NROW)
            for j in range(NCOL)
        ],
        dtype=np.int32,
    )
    root = zarr.open_group(str(fields), mode="a")
    mesh = root.require_group("mesh")
    mesh.create_array("vertices", data=vertices, overwrite=True)
    mesh.create_array("face_node_connectivity", data=faces, overwrite=True)
    mesh.attrs["structured_shape"] = [NROW, NCOL]


def _write_budget(run_dir: Path, *, drain_out: float) -> None:
    """Recharge 1 m3/s in, storage 0.4 m3/s, drains *drain_out*: closes at 0.6."""
    rows = [
        {
            "timestep": step,
            "zone_id": DOMAIN_BUDGET_ZONE,
            "component": component,
            "unit": "m3/s",
            "flux_in": flux_in,
            "flux_out": flux_out,
        }
        for step in range(N_STEPS)
        for component, flux_in, flux_out in (
            ("RCHA", 1.0, 0.0),
            ("DRN", 0.0, drain_out),
            ("STO-SS", 0.0, 0.4),
        )
    ]
    tables = run_dir / TABLES_DIRNAME
    tables.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(tables / "budgets.parquet")


def _seal_run(
    project: Path,
    *,
    site: str,
    recipe: str,
    head_offset: float,
    mesh_hash: str = MESH_HASH,
    version: int = 1,
    drain_out: float = 0.6,
) -> Path:
    """Write one sealed run ``runs/<site>-<recipe>[.vN]`` of the project."""
    case_id = f"{site}-{recipe}"
    name = case_id if version == 1 else f"{case_id}.v{version}"
    sim_id = _sim_id(name)
    fingerprint = f"fp_{site}"
    run_dir = project / "runs" / name
    run_dir.mkdir(parents=True)
    _write_fields(run_dir, head_offset=head_offset)
    _write_budget(run_dir, drain_out=drain_out)
    (run_dir / RUN_CONFIG_FILENAME).write_text('[simulation]\nname = "x"\n', encoding="utf-8")
    record = make_record(
        run=ManifestRun(
            sim_id=sim_id,
            name=name,
            name_stem=case_id,
            version=version,
            status="completed",
            project=project.name,
            case_id=case_id,
            recipe=recipe,
            rel_dir=f"runs/{name}",
            attempt=1,
            attempt_id=ATTEMPT_ID,
            solver="modflow6",
            flow_regime="transient",
            created_at=NOW,
            started_at=NOW,
            ended_at=NOW,
            duration_s=12.0,
        ),
        site=ManifestSite(
            name=site,
            gauge=site,
            fingerprint=fingerprint,
            x_outlet=OUTLET[0],
            y_outlet=OUTLET[1],
            crs="EPSG:2154",
        ),
        geometry=ManifestGeometry(
            n_cells=N_CELLS,
            n_layers=1,
            mesh_topology="structured",
            mesh_hash=mesh_hash,
            crs_epsg=2154,
        ),
        identity=make_identity(
            site=site,
            site_fingerprint=fingerprint,
            case_id=case_id,
            sim_id=sim_id,
            mesh_hash=mesh_hash,
        ),
        provenance=RunProvenance(sim_id=sim_id, tool={"name": "hydromodpy"}),
    )
    record.write(run_dir)
    return run_dir


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "bretagne"
    root.mkdir()
    (root / "project.toml").write_text("", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _index_is_never_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("hmp report compare opened the project index")

    monkeypatch.setattr(Catalog, "__init__", refuse)


def _tree(directory: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(directory)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_two_runs_of_one_case_give_diffs_maps_and_a_page(project: Path) -> None:
    reference = _seal_run(project, site="J0014010", recipe="mf6", head_offset=0.0)
    candidate = _seal_run(project, site="J0014010", recipe="bouss", head_offset=0.5, drain_out=0.65)
    before = {run: _tree(run) for run in (reference, candidate)}

    pages = compare_runs(["J0014010-mf6", "J0014010-bouss"], project_root=project)

    root = project / "summary" / "report" / "compare" / "J0014010-mf6-vs-J0014010-bouss"
    assert pages == [root / "web" / "index.html"]
    assert pages[0].is_file()
    html = pages[0].read_text(encoding="utf-8")
    assert 'id="section-case_check"' in html

    manifest = json.loads((root / "comparison_manifest.json").read_text(encoding="utf-8"))
    assert manifest["reference_simulation"] == "J0014010-mf6"
    assert manifest["case_check"]["status"] == "same_case"
    assert manifest["case_check"]["site_fingerprint"] == "fp_J0014010"
    assert [item["id"] for item in manifest["simulations"]] == ["J0014010-mf6", "J0014010-bouss"]
    assert {item["run_dir"] for item in manifest["simulations"]} == {
        str(reference),
        str(candidate),
    }

    report = (root / "comparison_report.md").read_text(encoding="utf-8")
    assert "run_folder=`../../../../runs/J0014010-mf6`" in report
    assert str(project) not in report

    differences = pd.read_csv(root / "comparison_differences.csv")
    head_map = differences.loc[differences["observable"] == "head_map_last"]
    assert not head_map.empty
    assert np.allclose(head_map["signed_error"].astype(float).abs(), 0.5)

    metrics = pd.read_csv(root / "comparison_metrics.csv")
    assert set(metrics["observable"]) >= {"head_map_last", "head_outlet_series"}
    assert (root / "observables.csv").is_file()
    figures = root / "comparison_figures"
    assert (figures / "head_map_last__fine_raster_map_comparison.png").is_file()
    assert (figures / "head_outlet_series__timeseries.png").is_file()

    closure = pd.read_csv(root / "numerical_closure_summary.csv").set_index("simulation_id")
    assert closure.loc["J0014010-mf6", "max_abs_closure_m3_s"] == pytest.approx(0.0, abs=1e-12)
    assert closure.loc["J0014010-bouss", "max_abs_closure_m3_s"] == pytest.approx(0.05)
    assert manifest["closure_status"] == "CHECK"

    # A report never writes into a sealed run.
    assert {run: _tree(run) for run in (reference, candidate)} == before


def test_the_outlet_series_is_read_at_the_outlet_of_the_manifests(project: Path) -> None:
    _seal_run(project, site="J0014010", recipe="mf6", head_offset=0.0)
    _seal_run(project, site="J0014010", recipe="bouss", head_offset=1.0)

    compare_runs(["J0014010-mf6", "J0014010-bouss"], project_root=project)

    root = project / "summary" / "report" / "compare" / "J0014010-mf6-vs-J0014010-bouss"
    rows = pd.read_csv(root / "observables.csv")
    series = rows.loc[rows["observable"] == "head_outlet_series"]
    # The outlet sits in the cell of row 1, column 1: index 5 of the grid.
    assert set(series["selected_cell_index"].astype(int)) == {5}
    assert len(series) == 2 * N_STEPS


def test_runs_on_two_meshes_are_refused_unless_allowed(project: Path) -> None:
    _seal_run(project, site="J0014010", recipe="coarse", head_offset=0.0)
    _seal_run(project, site="J0014010", recipe="fine", head_offset=0.2, mesh_hash="mesh0002")

    with pytest.raises(ComparisonCaseError, match="--allow-different-mesh"):
        compare_runs(["J0014010-coarse", "J0014010-fine"], project_root=project)

    out = project.parent / "mesh_study"
    compare_runs(
        ["J0014010-coarse", "J0014010-fine"],
        project_root=project,
        out=out,
        allow_different_mesh=True,
    )
    manifest = json.loads((out / "comparison_manifest.json").read_text(encoding="utf-8"))
    assert manifest["case_check"]["status"] == "different_mesh_allowed"
    assert manifest["case_check"]["mesh_hashes"] == {
        "J0014010-coarse": "mesh0001",
        "J0014010-fine": "mesh0002",
    }


def test_runs_of_two_sites_are_refused_without_by_site(project: Path) -> None:
    _seal_run(project, site="J0014010", recipe="base", head_offset=0.0)
    _seal_run(project, site="J0170000", recipe="base", head_offset=0.0)

    with pytest.raises(ComparisonCaseError, match="--by site"):
        compare_runs(["J0014010-base", "J0170000-base"], project_root=project)


def test_by_site_compares_two_recipes_on_each_site(project: Path) -> None:
    for site in ("J0014010", "J0170000"):
        _seal_run(project, site=site, recipe="calage_nm", head_offset=0.0)
        _seal_run(project, site=site, recipe="calage_tpe", head_offset=0.3)
    # An older version of a case is not the run its recipe names.
    _seal_run(project, site="J0170000", recipe="calage_tpe", head_offset=9.0, version=2)

    pages = compare_runs(["calage_nm", "calage_tpe"], project_root=project, by_site=True)

    root = project / "summary" / "report" / "compare" / comparison_name(["calage_nm", "calage_tpe"])
    assert pages == [
        root / "J0014010" / "web" / "index.html",
        root / "J0170000" / "web" / "index.html",
        root / "index.html",
    ]
    manifest = json.loads(
        (root / "J0170000" / "comparison_manifest.json").read_text(encoding="utf-8")
    )
    assert [item["id"] for item in manifest["simulations"]] == [
        "J0170000-calage_nm",
        "J0170000-calage_tpe.v2",
    ]


def test_a_reference_that_names_no_sealed_run_is_refused(project: Path) -> None:
    _seal_run(project, site="J0014010", recipe="mf6", head_offset=0.0)
    unsealed = project / "runs" / "J0014010-failed"
    unsealed.mkdir()

    with pytest.raises(ComparisonReferenceError, match="J0014010-failed"):
        compare_runs(["J0014010-mf6", "J0014010-failed"], project_root=project)


def test_the_command_maps_refusals_to_typed_exit_codes(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seal_run(project, site="J0014010", recipe="coarse", head_offset=0.0)
    _seal_run(project, site="J0014010", recipe="fine", head_offset=0.2, mesh_hash="mesh0002")
    monkeypatch.chdir(project)

    with pytest.raises(SystemExit) as missing:
        hmp_main(["report", "compare", "J0014010-coarse", "nowhere"])
    assert missing.value.code == EXIT_NOT_FOUND

    with pytest.raises(SystemExit) as mismatch:
        hmp_main(["report", "compare", "J0014010-coarse", "J0014010-fine"])
    assert mismatch.value.code == EXIT_VALIDATION

    hmp_main(["report", "compare", "J0014010-coarse", "J0014010-fine", "--allow-different-mesh"])
    page = (
        project
        / "summary"
        / "report"
        / "compare"
        / "J0014010-coarse-vs-J0014010-fine"
        / "web"
        / "index.html"
    )
    assert page.is_file()


@pytest.mark.parametrize(
    ("flags", "zone"),
    [([], "domain"), (["--budget-zone", "catchment"], "catchment")],
    ids=["default", "catchment"],
)
def test_the_command_forwards_the_budget_zone(
    project: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str], zone: str
) -> None:
    seen: dict[str, object] = {}

    def fake_compare_runs(refs, **options):
        seen.update(options)
        return []

    monkeypatch.setattr("hydromodpy.reporting.comparison.compare.compare_runs", fake_compare_runs)
    monkeypatch.chdir(project)

    hmp_main(["report", "compare", "a", "b", *flags])

    assert seen["budget_zone"] == zone


def test_by_site_joins_the_references_on_the_site(project: Path) -> None:
    for site in ("J0014010", "J0170000"):
        _seal_run(project, site=site, recipe="calage_nm", head_offset=0.0)
        _seal_run(project, site=site, recipe="calage_tpe", head_offset=0.3)
    # A site that only one reference holds is not compared.
    _seal_run(project, site="J0200000", recipe="calage_nm", head_offset=0.0)

    pages = compare_runs(["calage_nm", "calage_tpe"], project_root=project, by_site=True)

    root = project / "summary" / "report" / "compare" / comparison_name(["calage_nm", "calage_tpe"])
    table = pd.read_csv(root / "by_site.csv")
    assert table["site"].tolist() == ["J0014010", "J0170000"]
    assert table["calage_nm.run"].tolist() == ["J0014010-calage_nm", "J0170000-calage_nm"]
    assert table["calage_tpe.run"].tolist() == ["J0014010-calage_tpe", "J0170000-calage_tpe"]
    assert table["calage_nm.label"].notna().all()
    assert table["calage_nm.metric"].tolist() == ["nse", "nse"]
    assert table["calage_nm.window"].tolist() == ["2016-01-01/2020-12-31"] * 2
    index = pages[-1].read_text(encoding="utf-8")
    assert pages[-1] == root / "index.html"
    assert 'href="J0014010/web/index.html"' in index
    assert 'href="by_site.csv"' in index


def test_two_references_with_one_last_part_keep_their_own_columns() -> None:
    assert reference_labels(["calage_nm", "calage_tpe"]) == ["calage_nm", "calage_tpe"]
    assert reference_labels(["../a/runs/base", "../b/runs/base", "runs/tpe"]) == [
        "../a/runs/base",
        "../b/runs/base",
        "tpe",
    ]


def test_a_reference_given_twice_is_refused(project: Path) -> None:
    with pytest.raises(ComparisonCaseError, match="given twice"):
        compare_runs(["base", "base"], project_root=project)
