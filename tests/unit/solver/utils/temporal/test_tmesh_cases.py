"""Unit tests for temporal case config and runner."""

from __future__ import annotations

from pathlib import Path
import importlib.util
import json
import sys
import types
import uuid

import numpy as np
import pandas as pd


def _load_module(module_rel_path: str):
    repo_root = Path(__file__).resolve().parents[5]
    module_path = repo_root / module_rel_path
    module_name = f"_test_tmesh_case_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _FakeTMeshGeneration:
    """Fake temporal generator for case-runner tests."""

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)

    def run(self):
        genmtd = str(self.kwargs.get("genmtd", "synthetic_regular"))
        flow_regime = str(self.kwargs.get("flow_regime", "transient"))
        firstpersteady = bool(self.kwargs.get("firstpersteady", True))

        if genmtd == "from_chron":
            df = pd.read_csv(
                self.kwargs["chron_path"],
                sep=self.kwargs.get("chron_colsep", "\t"),
            )
            dates = pd.to_datetime(
                df[self.kwargs.get("chron_time_col", "Date")],
                format=self.kwargs.get("chron_dateformat", "%Y-%m-%d %H:%M:%S"),
            )
            perlen = (
                dates.diff()
                .iloc[1:]
                .dt.total_seconds()
                .to_numpy(dtype=float)
                / 86400.0
            )
            start_datetime = pd.Timestamp(dates.iloc[0])
        else:
            nper = int(self.kwargs.get("nper", 1))
            lenper = float(self.kwargs.get("lenper", 1.0))
            perlen = np.full(nper, lenper, dtype=float)
            raw_start = self.kwargs.get("start_datetime")
            start_datetime = pd.Timestamp("1970-01-01 00:00:00") if raw_start is None else pd.Timestamp(raw_start)

        nper_actual = int(len(perlen))
        raw_ntsp = self.kwargs.get("ntsp", 1)
        raw_tsmult = self.kwargs.get("tsmult", 1.0)
        nstp = np.full(nper_actual, int(raw_ntsp), dtype=int) if np.isscalar(raw_ntsp) else np.asarray(raw_ntsp, dtype=int)
        tsmult = np.full(nper_actual, float(raw_tsmult), dtype=float) if np.isscalar(raw_tsmult) else np.asarray(raw_tsmult, dtype=float)
        totim = np.cumsum(perlen).astype(float)
        datetimes = [start_datetime + pd.to_timedelta(float(t), unit="D") for t in totim]

        if flow_regime == "steady":
            steady = np.ones(nper_actual, dtype=bool)
        else:
            steady = np.zeros(nper_actual, dtype=bool)
            if firstpersteady and nper_actual > 0:
                steady[0] = True

        return types.SimpleNamespace(
            perlen=perlen,
            nstp=nstp,
            tsmult=tsmult,
            steady_state=steady,
            start_datetime=start_datetime,
            totim=totim,
            datetimes=datetimes,
        )


def test_load_tmesh_cases_toml_resolves_relative_paths(tmp_path: Path):
    cfg_module = _load_module("hydromodpy/solver/utils/temporal/cases/run_tmesh_config.py")

    chron = tmp_path / "chron.csv"
    chron.write_text("date\tvalue\n01/01/2020\t1\n02/01/2020\t2\n", encoding="utf-8")
    toml_path = tmp_path / "case.toml"
    toml_path.write_text(
        "[case]\n"
        "output_summary_json = \"outputs/summary.json\"\n"
        "output_figures_dir = \"outputs/figures\"\n"
        "[[case.scenarios]]\n"
        "id = \"chron_case\"\n"
        "genmtd = \"from_chron\"\n"
        "flow_regime = \"transient\"\n"
        "chron_path = \"chron.csv\"\n"
        "chron_dateformat = \"%d/%m/%Y\"\n"
        "chron_colsep = \"\\t\"\n"
        "chron_time_col = \"date\"\n",
        encoding="utf-8",
    )

    cfg = cfg_module.load_tmesh_cases_toml(toml_path)
    assert cfg.output_summary_json is not None
    assert cfg.output_figures_dir is not None
    assert cfg.output_summary_json.resolve() == (tmp_path / "outputs" / "summary.json").resolve()
    assert cfg.output_figures_dir.resolve() == (tmp_path / "outputs" / "figures").resolve()
    assert Path(cfg.scenarios[0].chron_path).resolve() == chron.resolve()


def test_run_tmesh_cases_from_toml_builds_summaries_and_writes_json(tmp_path: Path):
    run_module = _load_module("hydromodpy/solver/utils/temporal/cases/run_tmesh_case.py")
    run_module.TMesh_Generation = _FakeTMeshGeneration

    chron = tmp_path / "chron.csv"
    chron.write_text(
        "date\tvalue\n"
        "01/01/2020\t1\n"
        "03/01/2020\t2\n"
        "06/01/2020\t3\n",
        encoding="utf-8",
    )

    toml_path = tmp_path / "case.toml"
    toml_path.write_text(
        "[case]\n"
        "output_summary_json = \"outputs/summary.json\"\n"
        "output_figures_dir = \"outputs/figures\"\n"
        "[[case.scenarios]]\n"
        "id = \"steady_synth\"\n"
        "flow_regime = \"steady\"\n"
        "genmtd = \"synthetic_regular\"\n"
        "nper = 3\n"
        "lenper = 2\n"
        "[[case.scenarios]]\n"
        "id = \"chron_trans\"\n"
        "flow_regime = \"transient\"\n"
        "genmtd = \"from_chron\"\n"
        "chron_path = \"chron.csv\"\n"
        "chron_dateformat = \"%d/%m/%Y\"\n"
        "chron_colsep = \"\\t\"\n"
        "chron_time_col = \"date\"\n",
        encoding="utf-8",
    )

    summaries = run_module.run_tmesh_cases_from_toml(toml_path)
    assert set(summaries) == {"steady_synth", "chron_trans"}

    steady = summaries["steady_synth"]
    assert steady["nper"] == 3
    assert steady["perlen_days"] == [2.0, 2.0, 2.0]
    assert steady["steady_state"] == [True, True, True]
    assert steady["datetime_vector_size"] == 3
    assert steady["figure"] is not None

    chron_summary = summaries["chron_trans"]
    assert chron_summary["nper"] == 2
    assert chron_summary["perlen_days"] == [2.0, 3.0]
    assert chron_summary["steady_state"] == [True, False]
    assert chron_summary["datetime_vector_size"] == 2
    assert chron_summary["figure"] is not None

    out_json = tmp_path / "outputs" / "summary.json"
    assert out_json.exists()
    assert (tmp_path / "outputs" / "figures" / "steady_synth_modeltime_datetimes.png").exists()
    assert (tmp_path / "outputs" / "figures" / "chron_trans_modeltime_datetimes.png").exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "steady_synth" in payload
    assert "chron_trans" in payload
