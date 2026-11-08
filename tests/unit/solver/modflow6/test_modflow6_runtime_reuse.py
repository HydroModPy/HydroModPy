"""``run_processing`` writes the input files of a run once, and lists what it wrote.

A built run arrives unwritten: the whole simulation is written, then every file
under the folder of the model is listed in ``input_files``, the auxiliary folders
of a steady or cyclic start left out. A run whose files are on disk already, as
after a rerun, writes nothing and keeps the list it carries.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.solver.modflow6 import run as run_module
from hydromodpy.solver.modflow6.modflow6 import Modflow6
from hydromodpy.solver.modflow_common.options import ModflowRunOptions
from tests._helpers.model_factory import make_model

WRITTEN = ("mfsim.nam", "run.disv", "run.npf", "run.rcha.70.bin", "_solver_routing/d8.tif")


class _FakePackage:
    def __init__(self) -> None:
        self.write_calls = 0

    def write(self, *args, **kwargs) -> None:
        del args, kwargs
        self.write_calls += 1


class _FakeSimulation:
    """Writes the files of ``WRITTEN`` into its folder, and solves nothing."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.write_calls = 0
        self.run_calls = 0

    def write_simulation(self, *args, **kwargs) -> None:
        del args, kwargs
        self.write_calls += 1
        for name in WRITTEN:
            (self.folder / name).parent.mkdir(parents=True, exist_ok=True)
            (self.folder / name).write_text(name)

    def run_simulation(self, *args, **kwargs):
        del args, kwargs
        self.run_calls += 1
        return True, None


def _model(folder: Path) -> Modflow6:
    folder.mkdir(parents=True, exist_ok=True)
    model = object.__new__(Modflow6)
    model.sim = _FakeSimulation(folder)
    model.npf = _FakePackage()
    model.ic = _FakePackage()
    model.full_path = str(folder)
    model.nper = 1
    model.inputs = make_model()
    model.input_files = ("kept.npf",)
    return model


CASES = (
    ("an unwritten run writes the simulation", True, 1, WRITTEN),
    ("a written run writes nothing", False, 0, ("kept.npf",)),
)


@pytest.mark.parametrize(
    ("case", "write_model", "writes", "listed"), CASES, ids=[case[0] for case in CASES]
)
def test_a_run_writes_its_input_files_once(
    tmp_path: Path, case: str, write_model: bool, writes: int, listed: tuple[str, ...]
) -> None:
    del case
    model = _model(tmp_path / "run")

    success = Modflow6.processing(model, ModflowRunOptions(write_model=write_model, run_model=True))

    assert success is True
    assert model.sim.write_calls == writes
    assert model.sim.run_calls == 1
    assert model.npf.write_calls == 0
    assert model.input_files == tuple(sorted(listed))


@pytest.mark.parametrize(
    ("folders", "expected"),
    [
        ((), ("a.nam",)),
        (("_ssic/ssic",), ("a.nam",)),
        (("_cyc0/cyc0", "_cyc12/cyc12"), ("a.nam",)),
        (("_cycle/x",), ("_cycle/x/f", "a.nam")),
        (("_solver_routing",), ("_solver_routing/f", "a.nam")),
    ],
    ids=["no folder", "steady start", "spin-up cycles", "a folder named like one", "a sub folder"],
)
def test_the_listing_leaves_the_auxiliary_models_out(
    tmp_path: Path, folders: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    (tmp_path / "a.nam").write_text("a")
    for folder in folders:
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "f").write_text("f")

    assert run_module.written_input_files(tmp_path) == expected


def test_a_missing_folder_lists_nothing(tmp_path: Path) -> None:
    assert run_module.written_input_files(tmp_path / "absent") == ()
    assert run_module.written_input_files(None) == ()
