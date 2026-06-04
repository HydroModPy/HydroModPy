from __future__ import annotations

import json
from pathlib import Path

from hydromodpy.analysis.testbed.contracts import register_testbed_runner_provider
from hydromodpy.analysis.testbed.regional_lab import RegionalLabProfileLauncher
from hydromodpy.analysis.testbed.regional_lab_config import RegionalLabConfig

from ._regional_lab_builders import (
    write_csv_catalog,
    write_planned_configs,
    write_regional_lab_config,
)


def test_regional_lab_execution_stops_on_first_failure(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(
        tmp_path,
        execute=True,
        continue_on_error=False,
    )
    write_csv_catalog(tmp_path)
    write_planned_configs(tmp_path)

    calls: list[tuple[str, Path]] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            calls.append(("simulation", child_config))
            if len(calls) == 2:
                raise RuntimeError("planned failure")
            return {"name": child_config.stem}

        def run_comparison(self, child_config: Path) -> dict[str, object]:
            calls.append(("comparison", child_config))
            return {"comparison_id": child_config.stem}

    register_testbed_runner_provider(_FakeProvider())

    summary = RegionalLabProfileLauncher(config_path).run()

    assert summary["planned_case_count"] == 3
    assert summary["skipped_case_count"] == 1
    assert summary["executed_case_count"] == 2
    assert summary["failed_case_count"] == 1
    assert [(kind, path.name) for kind, path in calls] == [
        ("simulation", "run_headwater_100km2_outlet_2.toml"),
        ("simulation", "run_headwater_100km2_outlet_3.toml"),
    ]

    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    assert report["executed_case_count"] == 2
    assert report["failed_case_count"] == 1
    assert report["cases"][0]["status"] == "ok"
    assert report["cases"][1]["status"] == "failed"
    assert report["cases"][2]["status"] == "planned"
    assert report["skipped_cases"][0]["case_id"] == "backend_compare::headwater_100km2_outlet_3"


def test_regional_lab_executes_children_through_testbed_provider(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(
        tmp_path,
        execute=True,
    )
    write_csv_catalog(tmp_path)
    write_planned_configs(tmp_path)

    calls: list[tuple[str, Path, bool | None]] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            calls.append(("simulation", child_config, no_display))
            return {"name": child_config.stem}

        def run_comparison(self, child_config: Path) -> dict[str, object]:
            calls.append(("comparison", child_config, None))
            return {"comparison_id": child_config.stem}

    register_testbed_runner_provider(_FakeProvider())

    summary = RegionalLabProfileLauncher(config_path).run()

    assert summary["executed_case_count"] == 3
    assert summary["failed_case_count"] == 0
    assert [(kind, path.name) for kind, path, _ in calls] == [
        ("simulation", "run_headwater_100km2_outlet_2.toml"),
        ("simulation", "run_headwater_100km2_outlet_3.toml"),
        ("comparison", "compare_headwater_100km2_outlet_2.toml"),
    ]
    assert calls[0][2] is False

    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    assert [case["status"] for case in report["cases"]] == ["ok", "ok", "ok"]


def test_regional_lab_resume_skips_completed_cases(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(
        tmp_path,
        execute=True,
    )
    write_csv_catalog(tmp_path)
    write_planned_configs(tmp_path)

    output_root = tmp_path / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "regional_lab_report.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "sim_reference::headwater_100km2_outlet_2",
                        "status": "ok",
                    }
                ]
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )

    calls: list[tuple[str, Path]] = []

    class _FakeProvider:
        def run_simulation(self, child_config: Path, *, no_display: bool) -> dict[str, object]:
            calls.append(("simulation", child_config))
            return {"name": child_config.stem}

        def run_comparison(self, child_config: Path) -> dict[str, object]:
            calls.append(("comparison", child_config))
            return {"comparison_id": child_config.stem}

    register_testbed_runner_provider(_FakeProvider())

    summary = RegionalLabProfileLauncher(config_path).run()

    assert summary["executed_case_count"] == 2
    assert summary["reused_case_count"] == 1
    assert len(calls) == 2
    assert [(kind, path.name) for kind, path in calls] == [
        ("simulation", "run_headwater_100km2_outlet_3.toml"),
        ("comparison", "compare_headwater_100km2_outlet_2.toml"),
    ]

    report = json.loads(Path(summary["report_path"]).read_text(encoding="utf-8"))
    assert report["reused_case_count"] == 1
    assert report["cases"][0]["status"] == "skipped_existing_ok"


def test_regional_lab_rejects_unknown_recipe_launcher(tmp_path: Path) -> None:
    config_path = write_regional_lab_config(tmp_path, execute=False)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'launcher = "comparison"',
            'launcher = "unsupported"',
        ),
        encoding="utf-8",
    )
    write_csv_catalog(tmp_path)
    write_planned_configs(tmp_path)

    try:
        RegionalLabConfig.from_file(config_path)
    except ValueError as exc:
        assert "Unsupported regional_lab.recipe launcher 'unsupported'" in str(exc)
    else:
        raise AssertionError("unknown launcher should be rejected")
