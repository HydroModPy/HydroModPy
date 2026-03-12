from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from validation_cases.shared.cli import run_case_main


def test_run_case_main_passes_solver_to_supported_case(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def _run_comparison(*, caller_file, timeout, solver=None):
        captured["caller_file"] = caller_file
        captured["timeout"] = timeout
        captured["solver"] = solver
        return SimpleNamespace(
            result=SimpleNamespace(
                out_path=tmp_path,
                postprocess_dir=tmp_path / "_postprocess",
                solver_name=solver,
            )
        )

    def _plot_comparison(comparison, *, output_png, show_plot, dpi):
        del comparison, show_plot, dpi
        output_png.parent.mkdir(parents=True, exist_ok=True)
        output_png.write_text("ok", encoding="utf-8")
        return output_png

    run_case_main(
        argv=["--solver", "modflow6", "--timeout", "42", "--no-show"],
        description="demo",
        default_figure_name="figure.png",
        caller_file=__file__,
        run_comparison=_run_comparison,
        plot_comparison=_plot_comparison,
        build_metric_lines=lambda comparison: ("metric: ok",),
    )

    stdout = capsys.readouterr().out
    assert captured["caller_file"] == __file__
    assert captured["timeout"] == 42
    assert captured["solver"] == "modflow6"
    assert "Solver: modflow6" in stdout


def test_run_case_main_rejects_solver_for_unsupported_case(tmp_path: Path) -> None:
    def _run_comparison(*, caller_file, timeout):
        del caller_file, timeout
        return SimpleNamespace(
            result=SimpleNamespace(
                out_path=tmp_path,
                postprocess_dir=tmp_path / "_postprocess",
            )
        )

    with pytest.raises(SystemExit) as exc_info:
        run_case_main(
            argv=["--solver", "modflow6"],
            description="demo",
            default_figure_name="figure.png",
            caller_file=__file__,
            run_comparison=_run_comparison,
            plot_comparison=lambda comparison, *, output_png, show_plot, dpi: output_png,
            build_metric_lines=lambda comparison: (),
        )
    assert exc_info.value.code == 2
