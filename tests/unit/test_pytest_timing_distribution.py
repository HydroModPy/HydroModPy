from __future__ import annotations

import os
from pathlib import Path
import uuid

import pytest

from tests._helpers.pytest_timing_distribution import (
    _build_report,
    _load_test_timings,
    _parse_bins,
    _parse_status_filter,
)

_LOCAL_TMP_ROOT = (
    Path(os.environ["HYDROMODPY_TEST_SCRATCH_ROOT"])
    / "timing_reports"
    / "tmp_pytest_timing_distribution"
)
_LOCAL_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _new_local_work_dir() -> Path:
    path = _LOCAL_TMP_ROOT / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _write_sample_junitxml(path: Path) -> None:
    path.write_text(
        (
            "<?xml version='1.0' encoding='utf-8'?>\n"
            "<testsuite tests='4'>\n"
            "  <testcase classname='tests.unit.fast' name='test_a' time='0.001'/>\n"
            "  <testcase classname='tests.unit.fast' name='test_b' time='0.020'><skipped/></testcase>\n"
            "  <testcase classname='tests.unit.slow' name='test_c' time='1.200'/>\n"
            "  <testcase classname='tests.unit.fail' name='test_d' time='0.300'><failure/></testcase>\n"
            "</testsuite>\n"
        ),
        encoding="utf-8",
    )


def test_report_filters_statuses_and_exposes_quantiles() -> None:
    xml_path = _new_local_work_dir() / "sample.xml"
    _write_sample_junitxml(xml_path)

    timings = _load_test_timings(xml_path)
    report = _build_report(
        timings,
        junitxml_path=xml_path,
        bins=[0.01, 0.1, 1.0],
        top_n=5,
        status_filter={"passed"},
    )

    assert report["included_testcases"] == 2
    assert report["excluded_testcases"] == 2
    assert report["quantiles_s"]["max"] == pytest.approx(1.2)
    assert report["quantiles_s"]["p50"] == pytest.approx(0.6005)
    assert report["status_counts"]["skipped"] == 1
    assert report["top_slowest_tests"][0]["nodeid"].endswith("test_c")


def test_histogram_counts_cover_all_included_tests() -> None:
    xml_path = _new_local_work_dir() / "sample.xml"
    _write_sample_junitxml(xml_path)
    timings = _load_test_timings(xml_path)
    report = _build_report(
        timings,
        junitxml_path=xml_path,
        bins=[0.01, 0.1, 1.0],
        top_n=3,
        status_filter={"passed", "failed"},
    )

    histogram_total = sum(int(row["count"]) for row in report["histogram_s"])
    assert histogram_total == report["included_testcases"]
    assert report["included_testcases"] == 3


def test_parse_status_filter_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="Unsupported status values"):
        _parse_status_filter("passed,unknown")

    assert _parse_status_filter("passed,failed") == {"passed", "failed"}
    assert _parse_bins("0.01,0.1,1.0") == [0.01, 0.1, 1.0]
