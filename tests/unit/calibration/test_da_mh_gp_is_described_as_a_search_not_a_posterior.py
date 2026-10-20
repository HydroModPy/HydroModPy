"""``da_mh_gp`` is a sequential search method: nothing in its text speaks of a posterior.

The likelihood it builds scores the whole record as one residual, so the chain
is no posterior (audit decision m25). Two names stay because code reads them:
``posterior_samples`` and the ``posterior_mode`` metadata keys.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import hydromodpy

ROOT = Path(hydromodpy.__file__).resolve().parents[1]
KEPT_NAMES = re.compile(r"posterior_samples|posterior_mode(_logpost)?|calibration_posterior")


def _words_left(text: str) -> list[str]:
    stripped = KEPT_NAMES.sub("", text)
    return [line.strip() for line in stripped.splitlines() if "posterior" in line.lower()]


def _section(path: Path, start: str, stop: str) -> str:
    text = path.read_text(encoding="utf-8")
    begin = text.index(start)
    end = text.find(stop, begin)
    return text[begin:] if end < 0 else text[begin:end]


def test_the_adapter_never_says_posterior() -> None:
    path = ROOT / "hydromodpy/calibration/optim/adapters/da_mh_gp_adapter.py"
    assert _words_left(path.read_text(encoding="utf-8")) == []


def test_the_method_config_never_says_posterior() -> None:
    path = ROOT / "hydromodpy/calibration/optim/method_config.py"
    section = _section(path, "class DaMhGpMethodConfig", "\nCalibrationMethodConfig")
    assert _words_left(section) == []
    assert "plausible" not in section


def test_the_readme_never_says_posterior() -> None:
    assert _words_left((ROOT / "hydromodpy/calibration/README.md").read_text("utf-8")) == []


@pytest.mark.parametrize(
    ("page", "start", "stop"),
    [
        (
            "docs/source/theory/calibration/inverse-problem-formulation.md",
            "```{hmp-calibration-methods}",
            "## The width beside a value",
        ),
        (
            "docs/source/contribute/architecture/how-to/add-a-calibration-method.rst",
            "Distribution-valued methods",
            "Add a new figure",
        ),
    ],
)
def test_the_docs_never_call_the_chain_a_posterior(page: str, start: str, stop: str) -> None:
    assert _words_left(_section(ROOT / page, start, stop)) == []
