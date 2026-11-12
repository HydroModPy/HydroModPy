"""What a calibration reads from the budget and head files of a MODFLOW run.

MODFLOW signs a budget from the aquifer, so water leaving is negative. The drain outflow inside a
catchment and the release per cell are magnitudes of the negative part, water that enters releases
nothing, and a value that is not a number counts as no flow. The saturated thickness (m) is the
head clipped between the cell base and top. A budget file opens at either precision, because
MODFLOW 6 writes double and MODFLOW-NWT writes single.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import re
import struct

import flopy.utils.binaryfile as bf
import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.solver.modflow_common import calibration_extractors as extractors
from hydromodpy.solver.modflow_common.calibration_extractors import (
    ReleasePackage,
    _drain_outflow_on_mask,
    _positive_release_by_cell,
    _refuse_records_the_union_misses,
    _refuse_sibling_budgets_the_union_cannot_read,
    extract_release_flux_by_cell_from_cbc,
)


def _rows(nodes, flows) -> np.ndarray:
    rows = np.zeros(len(nodes), dtype=[("node", "<i4"), ("q", "<f8")])
    rows["node"] = nodes
    rows["q"] = flows
    return rows


# One row per drain record: the budget, the catchment mask and the outflow inside it, in the unit
# of the model. A dense array is summed on the mask, and a list record maps its 1-based nodes
# on the plan cells (node - 1) % ncpl, whatever the layer.
_DRAIN = [
    pytest.param(np.array([[-2.0, 3.0, -1.0]]), [True, True, False], 2.0, id="dense_negative_part"),
    pytest.param(np.array([[1.0, 3.0, 0.5]]), [True, True, True], 0.0, id="dense_inflow_only"),
    pytest.param(np.array([[-2.0, -0.0, 0.0]]), [True, True, True], 2.0, id="dense_negative_zero"),
    pytest.param(
        np.array([[-1.0, -1.0, -1.0], [-2.0, 0.0, 4.0]]),
        [True, False, True],
        4.0,
        id="dense_layers_add_up",
    ),
    pytest.param(
        _rows([1, 2, 3], [-2.0, 3.0, -1.0]), [True, True, False], 2.0, id="list_negative_part"
    ),
    pytest.param(
        _rows([1, 4], [-2.0, -3.0]), [True, False, False], 5.0, id="list_node_in_a_second_layer"
    ),
    pytest.param(_rows([2], [-1.0e-12]), [False, True, False], 1.0e-12, id="a_tiny_loss_counts"),
]


@pytest.mark.parametrize(("arr", "mask", "expected"), _DRAIN)
def test_drain_outflow_on_mask(arr, mask, expected) -> None:
    result = _drain_outflow_on_mask(arr, np.array(mask))

    assert result == pytest.approx(expected, abs=1e-18)
    assert result >= 0.0


def test_drain_budget_mesh_mismatch() -> None:
    with pytest.raises(ValueError, match="were not built for the same mesh"):
        _drain_outflow_on_mask(np.zeros((1, 4)), np.array([True, True, True]))


# One row per release field: the signed budget, the number of cells and the positive release
# per cell. A layer is summed onto the cell support.
_RELEASE = [
    pytest.param([-2.0, 3.0, 0.0], None, [2.0, 0.0, 0.0], id="negative_released_positive_kept_out"),
    pytest.param([-2.0, -0.0, -1.0e-12], None, [2.0, 0.0, 1.0e-12], id="signed_zero_and_tiny_loss"),
    pytest.param([np.nan, -1.0, np.inf], None, [0.0, 1.0, 0.0], id="not_a_number_is_no_release"),
    pytest.param([[-1.0, 2.0], [-3.0, -4.0]], 2, [4.0, 4.0], id="layers_added_per_cell"),
    pytest.param([[-1.0, 2.0], [3.0, -4.0]], 2, [1.0, 4.0], id="a_gain_in_one_layer_is_kept_out"),
]


@pytest.mark.parametrize(("signed", "n_cells", "expected"), _RELEASE)
def test_release_by_cell(signed, n_cells, expected) -> None:
    release = _positive_release_by_cell(np.array(signed), n_cells=n_cells)

    np.testing.assert_allclose(release, expected, rtol=1e-12, atol=0.0)
    assert (release >= 0.0).all()


@pytest.mark.parametrize(
    ("signed", "n_cells", "message"),
    [
        pytest.param([1.0, 2.0, 3.0], 2, "multiple of n_cells", id="not_a_multiple"),
        pytest.param([1.0, 2.0], 0, "n_cells must be > 0", id="no_cells"),
    ],
)
def test_release_refusals(signed, n_cells, message) -> None:
    with pytest.raises(ValueError, match=message):
        _positive_release_by_cell(np.array(signed), n_cells=n_cells)


class FakeHeadFile:
    """Two snapshots of a two-layer, three-cell model, layer-major."""

    def __init__(self, path):
        self.path = path

    def get_times(self):
        return [1.0, 2.0]

    def get_kstpkper(self):
        return [(0, 0), (0, 1)]

    def get_data(self, *, totim):
        if totim == 1.0:
            # layer 0: 12, 8, 1e30 (dry), and layer 1 must never be read when layer 0 is used
            return np.array([[[12.0, 8.0, 1e30]], [[-5.0, -5.0, -5.0]]])
        return np.array([[[20.0, 4.0, 6.0]], [[-5.0, -5.0, -5.0]]])

    def close(self):
        return None


@pytest.fixture
def head_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(bf, "HeadFile", FakeHeadFile)
    (tmp_path / "model.hds").write_text("", encoding="utf-8")
    return tmp_path


def thickness(folder, top, bottom, layer, **kwargs):
    return extractors.extract_saturated_thickness_by_cell_from_hds(
        folder,
        "model",
        top=np.array(top, dtype=float),
        bottom=np.array(bottom, dtype=float),
        layer=np.array(layer),
        **kwargs,
    )


NAN = np.nan
# One row per column geometry: top, base, layer read per cell, then the thickness of each cell at
# the two snapshots in m.
THICKNESS = [
    pytest.param(
        [10, 10, 10],
        [0, 0, 0],
        [0, 0, 0],
        [[10.0, 8.0, NAN], [10.0, 4.0, 6.0]],
        id="the head caps at the top and a dry cell is not a thickness",
    ),
    pytest.param(
        [30, 30, 30],
        [10, 10, 10],
        [0, 0, 0],
        [[2.0, 0.0, NAN], [10.0, 0.0, 0.0]],
        id="a head under the base gives zero",
    ),
    pytest.param(
        [10, 10, 10],
        [-10, -10, -10],
        [1, 0, -1],
        [[5.0, 18.0, NAN], [5.0, 14.0, NAN]],
        id="the top active cell of each column",
    ),
]


@pytest.mark.parametrize(("top", "bottom", "layer", "expected"), THICKNESS)
def test_saturated_thickness(head_folder, top, bottom, layer, expected) -> None:
    frame = thickness(head_folder, top, bottom, layer)

    np.testing.assert_allclose(frame.to_numpy(), expected)


def test_saturated_thickness_index(head_folder) -> None:
    index = pd.date_range("2020-01-01", periods=2, freq="D")

    frame = thickness(head_folder, [10, 10, 10], [0, 0, 0], [0, 0, 0], time_index=index)

    assert list(frame.index) == list(index)
    assert list(frame.columns) == [0, 1, 2]


def test_thickness_bounds_mismatch(head_folder) -> None:
    with pytest.raises(ValueError, match="top holds 3 cells but bottom holds 2"):
        thickness(head_folder, np.zeros(3), np.zeros(2), np.zeros(3, dtype=int))


def test_saturated_thickness_needs_the_head_file(tmp_path) -> None:
    with pytest.raises(ObservableNotAvailableError, match="HDS file not found"):
        thickness(tmp_path, np.zeros(3), np.zeros(3), np.zeros(3, dtype=int))


# The methods the extractors call must exist on the real flopy class. A stand-in once let
# the code call an invented API, every unit test passed and the first calibration trial crashed.


@pytest.mark.parametrize("name", ["get_indices", "get_record", "get_times", "close"])
def test_real_cellbudgetfile_has_the_method(name) -> None:
    assert callable(getattr(bf.CellBudgetFile, name, None))


def test_get_record_signature() -> None:
    # A bare positional index with full3D off keeps a list package as a record array.
    params = inspect.signature(bf.CellBudgetFile.get_record).parameters
    assert "idx" in params
    assert params["full3D"].default is False


def test_get_indices_selects_by_record_text() -> None:
    assert "text" in inspect.signature(bf.CellBudgetFile.get_indices).parameters


def test_extractor_calls_only_real_methods() -> None:
    called = set(re.findall(r"\bcbb\.([a-zA-Z_][a-zA-Z0-9_]*)", inspect.getsource(extractors)))
    unknown = sorted(name for name in called if not hasattr(bf.CellBudgetFile, name))

    assert not unknown, f"the extractor calls {unknown} on a CellBudgetFile that has none"


# FloPy guesses the precision of a budget file. On a MODFLOW 6 file its single-precision guess
# seeks to a nonsense offset and raises OSError, which its own fallback does not catch. Forcing a
# width is worse, since a wrong NWT read gives one nonsense record in place of eight without a
# word. So the width is detected first and a forced width is only the fallback.


def test_budget_width_fallback(monkeypatch) -> None:
    opened: list[str] = []

    class Budget:
        pass

    def fake(path, precision):
        opened.append(precision)
        if precision == "double":
            raise OSError(22, "Invalid argument")
        return Budget()

    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", fake, raising=True)

    assert isinstance(extractors.open_cell_budget("whatever.cbc"), Budget)
    assert opened == ["double", "single"]


def test_unreadable_budget_refused(monkeypatch) -> None:
    def fake(path, precision):
        raise OSError(22, f"Invalid argument at {precision}")

    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", fake, raising=True)

    with pytest.raises(ValueError, match="either precision"):
        extractors.open_cell_budget("broken.cbc")


def test_every_budget_opens_through_the_helper() -> None:
    # Only the body of open_cell_budget may call CellBudgetFile. Exempting its whole module let a
    # bare call next to it pass unseen, which a mutation test caught.
    root = pathlib.Path("hydromodpy/solver")
    helper_module = root / "modflow_common" / "calibration_extractors.py"
    helper = next(
        (
            node
            for node in ast.walk(ast.parse(helper_module.read_text(encoding="utf-8")))
            if isinstance(node, ast.FunctionDef) and node.name == "open_cell_budget"
        ),
        None,
    )
    assert helper is not None, f"open_cell_budget is gone from {helper_module}"
    exempt = range(helper.lineno, (helper.end_lineno or helper.lineno) + 1)

    offenders = []
    for path in root.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if path == helper_module and number in exempt:
                continue
            stripped = line.strip()
            if stripped.startswith("#") or "precision=" in line:
                continue
            if re.search(r"CellBudgetFile\s*\(", line):
                offenders.append(f"{path}:{number}: {stripped}")

    assert not offenders, f"these open a budget file without a precision: {offenders}"


# The release union must cover what the budget file holds. One guard refuses a release record
# that no declared package reads. The other refuses a package budget written to its own file
# next to the model one, only when the model budget is silent about that package, because
# budget_filerecord and save_flows are independent MODFLOW 6 options.

DRN = ReleasePackage(name="DRN", record_aliases=("DRN", "DRAIN", "DRAINS"))
SFR = ReleasePackage(name="SFR", record_aliases=("SFR",))
N_CELLS = 6
N_LAYERS = 1


def test_excluded_chd_not_refused() -> None:
    # Every MODFLOW-NWT catchment closes on a lateral constant head, so the mere presence of a
    # CONSTANT HEAD record is no reason to refuse. The model looked at it and gave a reason.
    reason = "no cell of it carries the stream role"

    _refuse_records_the_union_misses(
        [DRN],
        ["         DRN", "  CONSTANT HEAD"],
        excluded_records={"CHD": reason, "CONSTANT HEAD": reason},
    )


def test_record_guard_names_lak(tmp_path) -> None:
    # The union does not read LAK, so the run is refused, by the guard that names the records
    # and not by the file listed beside the budget.
    cbc = tmp_path / "cheze.cbc"
    cbc.write_bytes(b"")
    (tmp_path / "cheze.lak.cbc").write_bytes(b"")

    _refuse_sibling_budgets_the_union_cannot_read(cbc, [DRN], ["         DRN", "         LAK"])
    with pytest.raises(ObservableNotAvailableError, match="LAK"):
        _refuse_records_the_union_misses([DRN], ["         DRN", "         LAK"])


@pytest.mark.parametrize("package", ["sfr", "lak"])
def test_silent_sibling_budget_refused(tmp_path, package) -> None:
    cbc = tmp_path / "nancon.cbc"
    cbc.write_bytes(b"")
    (tmp_path / f"nancon.{package}.cbc").write_bytes(b"")

    with pytest.raises(ObservableNotAvailableError, match=package.upper()) as failure:
        _refuse_sibling_budgets_the_union_cannot_read(cbc, [DRN], ["         DRN"])

    assert "dry land" in str(failure.value)


def list_record(text: str, rows: list[tuple[int, int, float]]) -> bytes:
    """One IMETH 6 budget record as MODFLOW 6 writes it, rows as (node, node2, q in m3/s).

    Nodes are 1-based and q is signed from the aquifer, negative where a reach gains water.
    """
    head = struct.pack("<2i16s3i", 1, 1, text.rjust(16).encode(), N_CELLS, 1, -N_LAYERS)
    head += struct.pack("<i3d", 6, 1.0, 1.0, 1.0)
    for name in ("GWF_1", text.strip(), "GWF_1", text.strip()):
        head += name.ljust(16).encode()
    head += struct.pack("<i", 1)
    head += struct.pack("<i", len(rows))
    payload = np.array(rows, dtype=np.dtype([("node", "<i4"), ("node2", "<i4"), ("q", "<f8")]))
    return head + payload.tobytes()


def write_budget(directory, records: dict[str, list[tuple[int, int, float]]]):
    """Write a one-timestep model budget holding the given list records."""
    (directory / "nancon.cbc").write_bytes(
        b"".join(list_record(text, rows) for text, rows in records.items())
    )


# One row per budget: the records, the declared packages and the release per cell in m3/s. Cells
# are the support, so reaches on one cell net first and then the cell is clamped.
UNION_RELEASES = [
    pytest.param(
        {"SFR": [(3, 1, -2.0), (3, 2, -0.5), (4, 3, -1.0), (4, 4, 0.25)]},
        [SFR],
        [0.0, 0.0, 2.5, 0.75, 0.0, 0.0],
        id="reaches on one cell are summed before the clamp",
    ),
    pytest.param(
        {"DRN": [(1, 1, -1.0), (4, 2, -0.5)], "SFR": [(4, 1, -2.0), (6, 2, -1.5)]},
        [DRN, SFR],
        [1.0, 0.0, 0.0, 2.5, 0.0, 1.5],
        id="drain and stream land on one cell index",
    ),
]


@pytest.mark.parametrize(("records", "packages", "expected"), UNION_RELEASES)
def test_union_release(tmp_path, records, packages, expected) -> None:
    write_budget(tmp_path, records)

    released = extract_release_flux_by_cell_from_cbc(
        tmp_path, "nancon", packages=packages, n_cells=N_CELLS
    ).to_numpy()[0]

    np.testing.assert_allclose(released, expected)


def test_declared_sibling_budget_read(tmp_path) -> None:
    write_budget(tmp_path, {"SFR": [(2, 1, -4.0)]})
    (tmp_path / "nancon.sfr.cbc").write_bytes(b"")

    released = extract_release_flux_by_cell_from_cbc(
        tmp_path, "nancon", packages=[SFR], n_cells=N_CELLS
    ).to_numpy()[0]

    assert released[1] == pytest.approx(4.0)


def test_undeclared_record_refused(tmp_path) -> None:
    write_budget(tmp_path, {"DRN": [(1, 1, -1.0)], "SFR": [(4, 1, -2.0)]})

    with pytest.raises(ObservableNotAvailableError, match="release record"):
        extract_release_flux_by_cell_from_cbc(tmp_path, "nancon", packages=[DRN], n_cells=N_CELLS)
