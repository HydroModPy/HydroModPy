"""The methods the extractors call must exist on the REAL flopy class.

This module exists because of a concrete failure. `extract_discharge_from_cbc`
was rewritten to read by position, copying the pattern of the MODFLOW 6 budget
extractor. That extractor reads through hydromodpy's OWN reader, which exposes
``records`` and ``read_record``; ``flopy.utils.binaryfile.CellBudgetFile``
exposes neither. Every unit test passed, because the stand-ins implemented the
invented API, and the calibration crashed on the first trial after the solve.

A stand-in can only prove that the code does what the stand-in expects. These
tests interrogate the real class instead.
"""

from __future__ import annotations

import inspect

import flopy.utils.binaryfile as bf
import pytest

from hydromodpy.solver.modflow_common import calibration_extractors as cal


@pytest.mark.parametrize("name", ["get_indices", "get_record", "get_times", "close"])
def test_the_method_exists_on_the_real_cellbudgetfile(name: str) -> None:
    assert callable(getattr(bf.CellBudgetFile, name, None)), (
        f"CellBudgetFile has no {name!r}; the extractor calls it on the real class, "
        "and a stand-in that implements it would hide the failure until a run"
    )


def test_get_record_accepts_an_index_and_full3d() -> None:
    # The extractor passes a bare positional index and relies on full3D
    # defaulting to False, so a list package stays a record array.
    params = inspect.signature(bf.CellBudgetFile.get_record).parameters
    assert "idx" in params
    assert params["full3D"].default is False


def test_get_indices_selects_by_record_text() -> None:
    assert "text" in inspect.signature(bf.CellBudgetFile.get_indices).parameters


def test_the_extractor_calls_only_methods_the_real_class_has() -> None:
    """Every ``cbb.<name>`` in the module must be a real CellBudgetFile method.

    The guard that would have caught the crash: it reads the source for the
    calls actually made, instead of trusting a stand-in to describe them.
    """
    import re

    source = inspect.getsource(cal)
    called = set(re.findall(r"\bcbb\.([a-zA-Z_][a-zA-Z0-9_]*)", source))
    unknown = sorted(name for name in called if not hasattr(bf.CellBudgetFile, name))

    assert not unknown, f"the extractor calls {unknown} on a CellBudgetFile that has none"


class TestTheBudgetOpensAtEitherPrecision:
    """MODFLOW 6 writes DOUBLE, MODFLOW-NWT writes SINGLE, and FloPy guesses.

    Its guess reads a header and seeks past the record. On an MF6 budget the
    single-precision guess computes a nonsense offset and ``file.seek`` raises
    ``OSError(EINVAL)``, which FloPy's own fallback does not catch, so the guess
    never gets to try the other width. The call worked for years on NWT and
    broke the moment a calibration moved to MF6: seven trials crashed after
    their solve with ``OSError: [Errno 22] Invalid argument``.

    Forcing a width instead of asking is worse than it looks, because the wrong
    one does not raise: opening a single-precision NWT budget as double yields
    a file carrying one nonsense record in place of the eight it holds, and the
    DRAINS record every derived field needs disappears without a word. So the
    detection comes first and a forced width is only the fallback.
    """

    def test_flopy_detection_is_asked_before_a_forced_width(self, monkeypatch) -> None:
        from hydromodpy.solver.modflow_common import calibration_extractors as cal

        attempts: list[str] = []

        class _Budget:
            pass

        def _fake(path, precision=None):
            del path
            attempts.append(precision or "auto")
            return _Budget()

        monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", _fake, raising=True)
        result = cal.open_cell_budget("whatever.cbc")

        assert isinstance(result, _Budget)
        assert attempts == ["auto"], "a forced width must never be the first attempt"

    def test_an_oserror_on_one_width_does_not_escape(self, monkeypatch) -> None:
        from hydromodpy.solver.modflow_common import calibration_extractors as cal

        opened: list[str] = []

        class _Budget:
            pass

        def _fake(path, precision):
            del path
            opened.append(precision)
            if precision == "double":
                raise OSError(22, "Invalid argument")
            return _Budget()

        monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", _fake, raising=True)
        result = cal.open_cell_budget("whatever.cbc")

        assert isinstance(result, _Budget)
        assert opened == ["double", "single"]

    def test_a_file_no_width_can_read_is_refused_naming_both(self, monkeypatch) -> None:
        from hydromodpy.solver.modflow_common import calibration_extractors as cal

        def _fake(path, precision):
            del path
            raise OSError(22, f"Invalid argument at {precision}")

        monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", _fake, raising=True)
        with pytest.raises(ValueError, match="either precision"):
            cal.open_cell_budget("broken.cbc")

    def test_nothing_opens_a_budget_without_going_through_the_helper(self) -> None:
        """The regression to catch: a bare CellBudgetFile call coming back."""
        import pathlib
        import re

        root = pathlib.Path(cal_root := "hydromodpy/solver")
        helper_module = root / "modflow_common" / "calibration_extractors.py"
        offenders = []
        for path in root.rglob("*.py"):
            if path == helper_module:
                # The helper is where the widths are tried; that is its job.
                continue
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or "precision=" in line:
                    continue
                if re.search(r"CellBudgetFile\s*\(", line):
                    offenders.append(f"{path.relative_to(cal_root)}: {stripped}")

        assert not offenders, (
            "these open a budget file without a precision and will raise OSError on a "
            f"MODFLOW 6 file: {offenders}"
        )
