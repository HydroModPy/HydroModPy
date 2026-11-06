"""Mf6CellBudgetReader equivalence with flopy CellBudgetFile on synthetic files."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow6.extractors.cbc_reader import Mf6CellBudgetReader

_NCPL = 6
_NLAY = 2


def _pack_header1(kstp: int, kper: int, text: str, ndim1: int, ndim2: int, ndim3: int) -> bytes:
    return struct.pack("<2i16s3i", kstp, kper, text.rjust(16).encode(), ndim1, ndim2, ndim3)


def _array_record(kstp: int, kper: int, text: str, data: np.ndarray) -> bytes:
    head = _pack_header1(kstp, kper, text, _NCPL, 1, -_NLAY)
    head += struct.pack("<i3d", 1, 1.0, float(kper), float(kper))
    return head + np.asarray(data, dtype="<f8").tobytes()


def _list_record(
    kstp: int,
    kper: int,
    text: str,
    rows: list[tuple[int, int, float, float]],
    aux_names: tuple[str, ...] = ("AREA",),
) -> bytes:
    head = _pack_header1(kstp, kper, text, _NCPL, 1, -_NLAY)
    head += struct.pack("<i3d", 6, 1.0, float(kper), float(kper))
    for name in ("GWF_1", text.strip(), "GWF_1", text.strip()):
        head += name.ljust(16).encode()
    ndat = 1 + len(aux_names)
    head += struct.pack("<i", ndat)
    for name in aux_names:
        head += name.ljust(16).encode()
    head += struct.pack("<i", len(rows))
    dtype = np.dtype(
        [("node", "<i4"), ("node2", "<i4"), ("q", "<f8")] + [(name, "<f8") for name in aux_names]
    )
    payload = np.array(rows, dtype=dtype)
    return head + payload.tobytes()


@pytest.fixture
def cbc_path(tmp_path: Path) -> Path:
    rng = np.random.default_rng(7)
    chunks = []
    for kper in range(1, 4):
        chunks.append(_array_record(1, kper, "STO-SS", rng.normal(size=_NLAY * _NCPL)))
        chunks.append(_array_record(1, kper, "STO-SY", rng.normal(size=_NLAY * _NCPL)))
        chunks.append(
            _list_record(
                1,
                kper,
                "DRN",
                [(2, 0, -1.5 * kper, 4.0), (5, 0, -0.25, 9.0)],
            )
        )
        chunks.append(_list_record(1, kper, "WEL", [(7, 0, -3.0)], aux_names=()))
    path = tmp_path / "model.cbc"
    path.write_bytes(b"".join(chunks))
    return path


def test_headers_match_flopy(cbc_path: Path) -> None:
    import flopy.utils.binaryfile as bf

    flopy_cbb = bf.CellBudgetFile(str(cbc_path), precision="double")
    with Mf6CellBudgetReader(cbc_path) as reader:
        flopy_headers = flopy_cbb.recordarray
        assert len(reader.records) == len(flopy_headers)
        for record, expected in zip(reader.records, flopy_headers):
            assert record.kstp == int(expected["kstp"])
            assert record.kper == int(expected["kper"])
            assert record.text == expected["text"].decode().strip()
            assert record.imeth == int(expected["imeth"])
        names = [name.decode().strip() for name in flopy_cbb.get_unique_record_names()]
        assert reader.unique_record_names() == names
    flopy_cbb.close()


def test_payloads_match_flopy(cbc_path: Path) -> None:
    import flopy.utils.binaryfile as bf

    flopy_cbb = bf.CellBudgetFile(str(cbc_path), precision="double")
    with Mf6CellBudgetReader(cbc_path) as reader:
        for idx in range(len(reader.records)):
            expected = flopy_cbb.get_record(idx)
            got = reader.read_record(idx)
            if expected.dtype.names is None:
                assert got.shape == expected.shape
                np.testing.assert_array_equal(got, expected)
            else:
                assert got.dtype == expected.dtype
                np.testing.assert_array_equal(np.asarray(got), np.asarray(expected))
    flopy_cbb.close()


def test_aux_names_parsed(cbc_path: Path) -> None:
    with Mf6CellBudgetReader(cbc_path) as reader:
        drn = next(r for r in reader.records if r.text == "DRN")
        wel = next(r for r in reader.records if r.text == "WEL")
        assert drn.aux_names == ("AREA",)
        assert drn.nlist == 2
        assert wel.aux_names == ()
        assert wel.nlist == 1


def test_rejects_non_compact_file(tmp_path: Path) -> None:
    head = _pack_header1(1, 1, "RECHARGE", _NCPL, 1, _NLAY)  # positive nlay
    data = np.zeros(_NLAY * _NCPL, dtype="<f8").tobytes()
    path = tmp_path / "classic.cbc"
    path.write_bytes(head + data)
    with pytest.raises(ValueError, match="compact budget file"):
        Mf6CellBudgetReader(path)


def test_rejects_unknown_imeth(tmp_path: Path) -> None:
    head = _pack_header1(1, 1, "DRN", _NCPL, 1, -_NLAY)
    head += struct.pack("<i3d", 5, 1.0, 1.0, 1.0)
    path = tmp_path / "imeth5.cbc"
    path.write_bytes(head)
    with pytest.raises(ValueError, match="unsupported imeth"):
        Mf6CellBudgetReader(path)
