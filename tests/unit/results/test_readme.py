"""Run and session READMEs: what the run is, what it does not give, what a replay costs (s, MiB),
and the sha256 of the manifest they end with. No host, user or absolute path is named.
"""

from __future__ import annotations

import re

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.results.outcome import Outcome, OutcomeError
from hydromodpy.results.readme import manifest_sha256, render_run_readme, render_session_readme
from hydromodpy.results.record.manifest import ManifestPeriod
from hydromodpy.results.session.descriptor import (
    CostInterval,
    ParameterBound,
    ParameterWidth,
    ScoredSamples,
)
from hydromodpy.results.session.phase import FrozenValue, PhaseDescriptor
from hydromodpy.results.storage.run_profile import Profile, ProfileLine
from hydromodpy.results.validity_rules import LabelResult, Reason, label_for, run_quantities
from hydromodpy.schema.lineage import Lineage, Replay, ReplayDifference
from tests._helpers.run_records import NOW, make_record
from tests._helpers.session_documents import best_trial, session_descriptor, trial_line

LABEL = LabelResult(
    "calibrated", "3", (Reason.of("promoted", session_id="sess0001", status="completed"),), ()
)


def _outcome() -> Outcome:
    return Outcome(
        case_id="J0014010-base",
        attempt=2,
        attempt_id="7c1e" * 8,
        sim_id="9a4f" * 8,
        status="failed",
        exit_code=15,
        written_by="launcher",
        started_at=NOW,
        ended_at=NOW,
        host="node12",
        pid=4421,
        error=OutcomeError(type="SolverError", message="mf6 did not converge at stress period 51"),
    )


def test_run_readme(tmp_path):
    record = make_record()
    record.write(tmp_path)
    digest = manifest_sha256(tmp_path)

    text = render_run_readme(record, _outcome(), LABEL, manifest_sha256=digest)

    assert text.startswith("# J0014010-base\n")
    assert "`J0014010`: Nancon" in text
    assert "gauge `J0014010`, hubeau:J0014010" in text
    assert re.search(r"outlet WGS84: lon -1\.\d+, lat 48\.\d+", text)
    assert "2016-01-01 to 2020-12-31, 1827 day." in text
    assert "HydroModPy 2.0.0a5, solver `modflow6`, mesh engine `voronoi`" in text
    assert "code reproducible: no" in text
    assert "water budget 0.8 % (accepted up to 2 %)" in text
    assert "**calibrated** under rules 3." in text
    assert "NSE 0.81 on 2016-01-01 to 2020-12-31, 1827 samples, rule 1." in text
    assert "SolverError: mf6 did not converge at stress period 51" in text
    assert text.rstrip().endswith(f"sha256(manifest.json) = {digest}")


def test_run_readme_names_no_machine(tmp_path):
    record = make_record()
    record.write(tmp_path)

    text = render_run_readme(record, _outcome(), LABEL, manifest_sha256=manifest_sha256(tmp_path))

    assert "node12" not in text
    assert "/home/" not in text
    assert str(tmp_path) not in text


IN_TIME = "- The state inside a stress period: fields are stored once per period, at its end."
ONE_STATE = "- A change in time: the run is one steady state."
NO_FLOW = "- The flow between two cells. Set `keep_face_flows = true` under `[simulation.results]` to keep it."
NO_PARTICLES = "- A residence time: the run has no particle tracking."


@pytest.mark.parametrize(
    ("period", "regime", "stored", "expected"),
    [
        pytest.param(
            ManifestPeriod(),
            "transient",
            frozenset({"fields/head"}),
            [ONE_STATE, NO_FLOW, NO_PARTICLES],
            id="no_period_is_one_state",
        ),
        pytest.param(
            None,
            "steady",
            frozenset({"fields/head"}),
            [ONE_STATE, NO_FLOW, NO_PARTICLES],
            id="steady_regime_with_dates_is_one_state",
        ),
        pytest.param(
            None,
            "transient",
            frozenset({"fields/head", "fields/face_flow"}),
            [IN_TIME, NO_PARTICLES],
            id="transient_with_the_flow_between_cells",
        ),
        pytest.param(
            None,
            "transient",
            frozenset({"fields/head", "fields/particles/x"}),
            [IN_TIME, NO_FLOW],
            id="transient_with_pathlines",
        ),
        pytest.param(
            None,
            "transient",
            frozenset({"fields/face_flow", "fields/particles/x"}),
            [IN_TIME],
            id="transient_with_both",
        ),
        pytest.param(
            None,
            "transient",
            frozenset({"final_state/head", "tables/budget/flow", "fields/mesh/open_water"}),
            [IN_TIME, NO_FLOW, NO_PARTICLES],
            id="other_keys_prove_nothing",
        ),
    ],
)
def test_what_the_run_does_not_give(period, regime, stored, expected) -> None:
    record = make_record()
    record = record.model_copy(
        update={
            "run": record.run.model_copy(update={"flow_regime": regime}),
            **({} if period is None else {"period": period}),
        }
    )

    text = render_run_readme(
        record, None, LABEL, manifest_sha256="0" * 64, stored=stored, writes_face_flow=True
    )

    start = text.index("## What this run does not give")
    section = text[start : text.index("## Cost of a replay")].strip().splitlines()
    assert section == ["## What this run does not give", "", *expected]


@pytest.mark.parametrize(
    ("writes_face_flow", "lineage_kind", "expected"),
    [
        pytest.param(True, None, NO_FLOW, id="the_setting_keeps_it"),
        pytest.param(
            False,
            None,
            "- The flow between two cells: the solver of this run does not compute it.",
            id="the_solver_does_not_write_it",
        ),
        pytest.param(
            True,
            "trial",
            "- The flow between two cells: a kept calibration trial keeps none.",
            id="a_kept_trial_keeps_none",
        ),
        pytest.param(
            None,
            None,
            "- The flow between two cells: the run did not keep it.",
            id="the_caller_does_not_say",
        ),
    ],
)
def test_face_flow_line(writes_face_flow, lineage_kind, expected) -> None:
    record = make_record()
    record = record.model_copy(update={"lineage": Lineage(kind=lineage_kind)})

    text = render_run_readme(
        record,
        None,
        LABEL,
        manifest_sha256="0" * 64,
        stored=frozenset({"fields/head"}),
        writes_face_flow=writes_face_flow,
    )

    flow_lines = [line for line in text.splitlines() if "flow between two cells" in line]
    assert flow_lines == [expected]


def test_face_flow_setting_is_a_config_key() -> None:
    found = re.search(r"Set `(\w+) = true` under `\[([\w.]+)\]`", NO_FLOW)
    assert found is not None
    setting, table = found.groups()
    model = HydroModPyConfig
    for part in table.split("."):
        model = model.model_fields[part].annotation

    assert model.model_fields[setting].annotation is bool


def test_label_rendered(tmp_path):
    record = make_record()
    result = label_for(
        record.checks, hydromodpy_version="2.0.0a4", quantities=run_quantities(solver="modflow6")
    )
    text = render_run_readme(record, None, result, manifest_sha256="0" * 64)
    assert "**exploratory** under rules 3." in text
    assert "known issues: mf6_computation_top" in text


def _line(kind, name, seconds, *, attempt=1, reused="no", key=None, rss=None) -> ProfileLine:
    return ProfileLine(
        kind=kind,
        name=name,
        attempt=attempt,
        started_at=NOW,
        duration_s=seconds,
        max_rss_mb=rss,
        reused=reused,
        key=key,
    )


def _replay_text(profile: Profile | None) -> str:
    text = render_run_readme(make_record(), None, LABEL, manifest_sha256="0" * 64, profile=profile)
    start = text.index("## Cost of a replay")
    return text[start : text.index("## Where is what")].strip()


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        pytest.param(
            (
                _line("step", "build_mesh", 1.5, rss=400.0),
                _line("step", "run_solver", 9.0, rss=900.0),
                _line("solve", "flow_main::modflow6", 8.5),
            ),
            "A replay of this run computes 2 steps in 10.5 s, 8.5 s of it in the solve, "
            "and needs up to 900 MiB of memory.",
            id="one_attempt",
        ),
        pytest.param(
            (
                _line("step", "load_data", 1.0),
                _line("step", "run_solver", 3.0),
                _line("step", "load_data", 0.2, attempt=2, reused="prefix"),
                _line("step", "run_solver", 9.0, attempt=2),
                _line("solve", "flow_main::modflow6", 8.5, attempt=2),
            ),
            "A replay of this run computes 2 steps in 10.0 s, 8.5 s of it in the solve.",
            id="a_resumed_run_counts_each_step_once",
        ),
        pytest.param(
            (_line("step", "build_mesh", 600.0), _line("step", "run_solver", 7500.0)),
            "A replay of this run computes 2 steps in 2 h 15 min.",
            id="hours",
        ),
        pytest.param(
            (_line("step", "build_mesh", 90.0),),
            "A replay of this run computes 1 step in 90.0 s.",
            id="seconds_up_to_two_minutes",
        ),
        pytest.param(
            (_line("step", "build_mesh", 130.0),),
            "A replay of this run computes 1 step in 2 min.",
            id="minutes",
        ),
    ],
)
def test_replay_cost(lines, expected) -> None:
    text = _replay_text(Profile(lines=lines))

    assert expected in text
    assert "`profile.json`, measured on the machine that ran it." in text


def test_replay_cost_on_an_empty_store() -> None:
    profile = Profile(lines=(_line("step", "build_geographic", 0.4, reused="store", key="t/ab"),))

    assert "A replay on an empty store computes them too" in _replay_text(profile)


def test_session_readme():
    descriptor = session_descriptor(
        "J0014010-calage",
        site="J0014010",
        session_id="sess0001",
        method="tpe",
        cost_name="nse_log",
        bounds={"K": ParameterBound(lower=1e-7, upper=1e-4, search_space="log", units="m/s")},
        cost_label="1 - nse_log",
        widths={"K": ParameterWidth(interval=CostInterval(lower=2e-5, upper=9e-5))},
        scored=[ScoredSamples(window="calibration", case_id="c", output="hydrograph", n=1828)],
        best=best_trial(
            7,
            cost=-0.84,
            parameters={"K": 6.4e-5},
            case="J0014010-calage",
            sim_id="9a4f" * 8,
            rel_dir="runs/J0014010-calage",
        ),
        status="completed",
        ended_at=NOW,
    )
    trials = [trial_line(n, phase="transient_sy") for n in range(1, 8)]
    phases = [
        PhaseDescriptor(
            phase_id="p1", name="steady_k", index=0, status="completed", best=best_trial(3)
        ),
        PhaseDescriptor(
            phase_id="p2",
            name="transient_sy",
            index=1,
            status="completed",
            frozen={
                "K": FrozenValue(value=6.1e-6, mode="replace", from_phase="steady_k"),
            },
        ),
    ]

    text = render_session_readme(
        descriptor, trials, LABEL, phases=phases, manifest_sha256="ab" * 32
    )

    assert text.startswith("# Calibration J0014010-calage\n")
    assert "site `J0014010`, method `tpe`, cost `nse_log`, status **completed**" in text
    assert "- `K`: 1e-07 to 0.0001 m/s, log" in text
    assert "7 trials in `trials.jsonl`" in text
    assert "| steady_k | completed | 0 | none | 3 | not recorded |" in text
    assert "K = 6.1e-06 (steady_k)" in text
    assert "- trial 7, cost -0.84 (1 - nse_log)\n" in text
    assert "- `K` = 6.4e-05 m/s, interval 2e-05 to 9e-05\n" in text
    assert "- scored on hydrograph 1828 pair(s)\n" in text
    assert "calibrated run of `J0014010-calage`: `runs/J0014010-calage` (sim_id `" in text
    assert text.rstrip().endswith(f"sha256(manifest.json) = {'ab' * 32}")


def _replay_lineage(**fields):
    return Lineage(kind="replay", replay=Replay(**fields))


def test_replay_lineage():
    record = make_record(
        lineage=_replay_lineage(
            of="9a4f" * 8,
            source="copy",
            source_version="2.0.0a5",
            basis="float64",
            class_="deviation",
            differs={"fields/head": ReplayDifference(max_abs=0.01, rel_l2=0.001)},
        )
    )
    text = render_run_readme(record, None, LABEL, manifest_sha256="0" * 64)

    assert "replay of `" in text and "read from a copy of version 2.0.0a5" in text
    assert "values float64, class deviation" in text
    assert "moved: `fields/head`" in text


def test_replay_lineage_without_a_basis():
    record = make_record(
        lineage=_replay_lineage(
            of="9a4f" * 8,
            source="run",
            source_version="2.0.0a5",
            basis="none",
        )
    )
    text = render_run_readme(record, None, LABEL, manifest_sha256="0" * 64)

    assert "read from a run of version 2.0.0a5, values none" in text
    assert "class bit" not in text and "class deviation" not in text
    assert "moved:" not in text
