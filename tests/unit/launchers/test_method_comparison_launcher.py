from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.config.toml_loader import load_toml_with_base_config
from launchers.method_comparison.config import MethodComparisonConfig
from launchers.method_comparison.launcher import MethodComparisonLauncher
from launchers.method_comparison.metrics import build_comparison_metrics
from launchers.method_comparison.runtime import (
    extract_observable_rows,
    materialize_variant_config,
)


def _load_launchers_main_module():
    module_path = Path(__file__).resolve().parents[3] / "launchers" / "__main__.py"
    spec = importlib.util.spec_from_file_location(
        "launchers_main_method_comparison_test_module",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_base_simulation_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[workspace]",
                'project_root = "project/base_case"',
                "",
                "[simulation]",
                'run_id = "base_run"',
                "",
                "[[simulation.process]]",
                'id = "flow_main"',
                'type = "flow"',
                'solvers = ["modflow6"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_method_comparison_config(path: Path, run_folder: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_compare"',
                'output_root = "comparison_outputs"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "mf6_demo"',
                'solver = "modflow6"',
                'mesh_mode = "mesh_catchment"',
                f'run_folder = "{run_folder.as_posix()}"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_at_point"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "x = 10.0",
                "y = 0.0",
                'time = "last"',
                'unit = "m"',
                "",
                "[[method_comparison.observable]]",
                'name = "outlet_accumulation"',
                'variable = "accumulation_flux"',
                'support = "outlet"',
                "cell_index = 1",
                'time = "last"',
                'reducer = "max"',
                'unit = "m/day"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_fake_run_folder(
    run_folder: Path,
    bundle_dir: Path,
    *,
    head_offset: float = 0.0,
    accumulation_offset: float = 0.0,
) -> None:
    postprocess_dir = run_folder / "_postprocess"
    postprocess_dir.mkdir(parents=True, exist_ok=True)
    np.save(
        postprocess_dir / "watertable_elevation.npy",
        {
            0: np.asarray([10.0, 20.0, 30.0]) + head_offset,
            1: np.asarray([11.0, 21.0, 31.0]) + head_offset,
        },
    )
    np.save(
        postprocess_dir / "accumulation_flux.npy",
        {
            0: np.asarray([0.1, 0.4, 0.2]) + accumulation_offset,
            1: np.asarray([0.3, 0.8, 0.5]) + accumulation_offset,
        },
    )
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "cells.csv").write_text(
        "\n".join(
            [
                "cell_id,centroid_x,centroid_y",
                "0,0.0,0.0",
                "1,10.0,0.0",
                "2,20.0,0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_folder / "_metrics.json").write_text(
        json.dumps({"mesh_output_exchange_bundle_dir": str(bundle_dir)}),
        encoding="utf-8",
    )


def test_method_comparison_config_resolves_paths(tmp_path: Path) -> None:
    run_folder = tmp_path / "runs" / "mf6_demo"
    config_path = tmp_path / "config_method_comparison.toml"
    _write_method_comparison_config(config_path, run_folder)

    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    assert cfg.comparison_root == (tmp_path / "comparison_outputs").resolve()
    assert cfg.method_comparison.comparison_id == "demo_compare"
    assert cfg.resolve_variant_run_folder(
        cfg.method_comparison.variant[0]
    ) == run_folder.resolve()
    assert cfg.method_comparison.observable[1].reducer == "max"


def test_materialize_variant_config_writes_base_overlay(tmp_path: Path) -> None:
    base_config = tmp_path / "run_flow_common.toml"
    _write_base_simulation_config(base_config)
    config_path = tmp_path / "config_method_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_compare"',
                'base_simulation_config = "run_flow_common.toml"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "bouss_demo"',
                'solver = "boussinesq"',
                "",
                "[method_comparison.variant.overlay.mesh_input]",
                'bundle_dir = "results_stable/mesh/bundle"',
                "",
                "[[method_comparison.observable]]",
                'name = "head_cell"',
                'variable = "watertable_elevation"',
                'support = "point"',
                "cell_index = 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )

    generated = materialize_variant_config(
        cfg=cfg,
        variant=cfg.method_comparison.variant[0],
    )

    assert generated is not None
    raw = load_toml_with_base_config(generated)
    assert raw["simulation"]["run_id"] == "bouss_demo"
    assert raw["simulation"]["process"][0]["solvers"] == ["boussinesq"]
    assert raw["mesh_input"]["bundle_dir"] == "results_stable/mesh/bundle"


def test_extract_observable_rows_reads_point_and_strict_outlet(tmp_path: Path) -> None:
    run_folder = tmp_path / "run"
    bundle_dir = tmp_path / "bundle"
    _write_fake_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_method_comparison.toml"
    _write_method_comparison_config(config_path, run_folder)
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )
    variant = cfg.method_comparison.variant[0]

    rows = extract_observable_rows(
        comparison_id="demo_compare",
        variant=variant,
        run_folder=run_folder,
        observables=tuple(cfg.method_comparison.observable),
    )

    assert len(rows) == 2
    head = next(row for row in rows if row["observable"] == "head_at_point")
    outlet = next(row for row in rows if row["observable"] == "outlet_accumulation")
    assert head["value"] == 21.0
    assert head["selected_cell_index"] == "1"
    assert outlet["value"] == 0.8
    assert outlet["selection"] == "declared_cell"
    assert outlet["selected_cell_index"] == "1"
    assert outlet["time_index"] == 1
    assert outlet["comparison_time_key"] == "time_index:1"


def test_outlet_without_location_requires_explicit_proxy_opt_in(tmp_path: Path) -> None:
    config_path = tmp_path / "config_method_comparison.toml"
    config_path.write_text(
        "\n".join(
            [
                "[method_comparison]",
                'comparison_id = "demo_compare"',
                "run_variants = false",
                "",
                "[[method_comparison.variant]]",
                'id = "mf6_demo"',
                'run_folder = "run"',
                "",
                "[[method_comparison.observable]]",
                'name = "outlet_accumulation"',
                'variable = "accumulation_flux"',
                'support = "outlet"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="outlet observables require"):
        MethodComparisonConfig.from_toml(
            load_toml_with_base_config(config_path),
            config_path=config_path,
        )


def test_method_comparison_launcher_reuses_existing_run_folder(tmp_path: Path) -> None:
    run_folder = tmp_path / "run"
    bundle_dir = tmp_path / "bundle"
    _write_fake_run_folder(run_folder, bundle_dir)
    config_path = tmp_path / "config_method_comparison.toml"
    _write_method_comparison_config(config_path, run_folder)

    summary = MethodComparisonLauncher(config_path).run()

    manifest_path = Path(summary["manifest_path"])
    observables_csv = Path(summary["observables_csv"])
    assert manifest_path.exists()
    assert observables_csv.exists()
    assert summary["n_observable_rows"] == 2
    with observables_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["observable"] for row in rows} == {
        "head_at_point",
        "outlet_accumulation",
    }
    assert Path(summary["comparison_metrics_csv"]).exists()
    assert Path(summary["comparison_differences_csv"]).exists()


def test_build_comparison_metrics_against_reference(tmp_path: Path) -> None:
    reference_run = tmp_path / "reference"
    candidate_run = tmp_path / "candidate"
    bundle_dir = tmp_path / "bundle"
    _write_fake_run_folder(reference_run, bundle_dir)
    _write_fake_run_folder(
        candidate_run,
        bundle_dir,
        head_offset=2.0,
        accumulation_offset=0.1,
    )
    config_path = tmp_path / "config_method_comparison.toml"
    _write_method_comparison_config(config_path, reference_run)
    cfg = MethodComparisonConfig.from_toml(
        load_toml_with_base_config(config_path),
        config_path=config_path,
    )
    reference_variant = cfg.method_comparison.variant[0]
    candidate_variant = reference_variant.model_copy(
        update={"id": "candidate", "label": "candidate"}
    )

    rows = []
    rows.extend(
        extract_observable_rows(
            comparison_id="demo_compare",
            variant=reference_variant,
            run_folder=reference_run,
            observables=tuple(cfg.method_comparison.observable),
        )
    )
    rows.extend(
        extract_observable_rows(
            comparison_id="demo_compare",
            variant=candidate_variant,
            run_folder=candidate_run,
            observables=tuple(cfg.method_comparison.observable),
        )
    )

    detail, summary = build_comparison_metrics(rows, reference_variant="mf6_demo")

    assert len(detail) == 2
    summary_by_observable = {row["observable"]: row for row in summary}
    assert summary_by_observable["head_at_point"]["mae"] == 2.0
    assert summary_by_observable["outlet_accumulation"]["mae"] == pytest.approx(0.1)


def test_launchers_cli_method_comparison_run_dispatches_to_launcher(monkeypatch) -> None:
    module = _load_launchers_main_module()
    captured: dict[str, Path] = {}

    config_path = Path("sample_method_comparison.toml")

    def _fake_runner(path: Path) -> None:
        captured["config"] = path

    monkeypatch.setattr(module, "_run_method_comparison_launcher", _fake_runner)

    code = module.main(["method-comparison", "run", str(config_path)])

    assert code == 0
    assert captured["config"] == config_path.resolve()
