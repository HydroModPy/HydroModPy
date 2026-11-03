"""``methods.md`` says what each stage scored: metric, dates and pair count.

The paragraph described the scoring in the generic words of the protocol,
"scored after the first year of the run, the spin-up, unless the file declares
a scoring window", which no longer even holds once ``[metrics] window`` is
set. A reader citing the paragraph could not tell which dates the cost rests
on, which metric it is, or on how many pairs. The paragraph now ends on what
each stage minimised, read off its report.
"""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.calibration.config import MatchingHydrographicNetworkOptions, validate_calib_output
from hydromodpy.calibration.protocols import protocol_record
from hydromodpy.calibration.runners.staged_runner import _methods_paragraph_for

NAME = "matching_hydrographic_network"


def _run(name: str, extra: dict) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        report=SimpleNamespace(best_parameters={"K": 1.0e-5}, best_cost=0.3, extra=extra),
    )


def _paragraph() -> str:
    net = validate_calib_output({"support": "network", "stream_geometry_path": "map.gpkg"})
    cfg = SimpleNamespace(
        protocol=MatchingHydrographicNetworkOptions(name=NAME, storage="Sy"),
        outputs={"net": net},
    )
    runs = [
        _run(
            "steady_conductivity",
            {"cost_metric": "distance_gap", "cost_window": "no window, every paired sample"},
        ),
        _run(
            "transient_storage",
            {
                "cost_metric": "1 - nse_log",
                "cost_window": "window 2016-01-01 to 2020-12-31",
                "cost_samples": {
                    "hydrograph": {"n_paired": 1828, "start": "2016-01-01", "end": "2021-01-01"}
                },
            },
        ),
    ]
    text = _methods_paragraph_for(cfg, runs, [])
    assert text is not None
    return text


def test_each_stage_names_its_metric_and_the_pairs_of_its_cost() -> None:
    text = _paragraph()

    assert (
        "Scoring: stage 1 (steady_conductivity) minimised distance_gap; stage 2 "
        "(transient_storage) minimised 1 - nse_log on hydrograph 1828 pair(s), period "
        "ends 2016-01-01 to 2021-01-01, at its best trial (window 2016-01-01 to 2020-12-31)."
    ) in text


def test_the_stage_text_names_the_window_of_the_run_as_a_default() -> None:
    transient = protocol_record(NAME)["stages"][1]

    assert "[metrics] window" in transient
