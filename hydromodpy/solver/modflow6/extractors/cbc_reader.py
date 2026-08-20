"""Single-pass index reader for MODFLOW 6 cell-by-cell budget files.

FloPy's ``CellBudgetFile`` builds its index with per-record Python lists and
linear membership checks, which turns quadratic over multi-thousand-period
chronicles. MODFLOW 6 budget files only contain compact headers with IMETH 1
(full arrays) or IMETH 6 (lists), always in double precision, so a dedicated
scanner stays small. Record payloads match FloPy's ``get_record`` byte for
byte; the equivalence is pinned by unit tests.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_HEADER1 = struct.Struct("<2i16s3i")  # kstp, kper, text, ndim1, ndim2, ndim3
_HEADER2 = struct.Struct("<i3d")  # imeth, delt, pertim, totim
_NAMES_BLOCK = 64  # modelnam, paknam, modelnam2, paknam2 (4 x 16 chars)
_REAL_BYTES = 8


@dataclass(frozen=True, slots=True)
class CbcRecord:
    """Header of one budget record; ``kstp``/``kper`` are 1-based as stored."""

    kstp: int
    kper: int
    text: str
    imeth: int
    ndim1: int
    ndim2: int
    ndim3: int
    nlist: int
    aux_names: tuple[str, ...]
    data_pos: int


class Mf6CellBudgetReader:
    """Sequential header scan plus random access to record payloads."""

    def __init__(self, path: str | Path) -> None:
        self._file = open(Path(path), "rb")
        try:
            self.records: tuple[CbcRecord, ...] = tuple(self._scan())
        except Exception:
            self._file.close()
            raise

    def __enter__(self) -> Mf6CellBudgetReader:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._file.close()

    def unique_record_names(self) -> list[str]:
        """Record texts in file order, first occurrence kept."""
        seen: dict[str, None] = {}
        for record in self.records:
            seen.setdefault(record.text, None)
        return list(seen)

    def read_record(self, idx: int) -> np.ndarray:
        """Return the payload of record ``idx``.

        IMETH 1 gives a float64 array shaped ``(nlay, nrow, ncol)``; IMETH 6
        gives a recarray with ``node``, ``node2``, ``q`` and auxiliary fields,
        matching FloPy's ``CellBudgetFile.get_record``.
        """
        record = self.records[idx]
        self._file.seek(record.data_pos)
        if record.imeth == 1:
            nlay = abs(record.ndim3)
            shape = (nlay, record.ndim2, record.ndim1)
            count = nlay * record.ndim2 * record.ndim1
            data = np.fromfile(self._file, dtype=np.float64, count=count)
            return data.reshape(shape)
        dtype = np.dtype(
            [("node", np.int32), ("node2", np.int32), ("q", np.float64)]
            + [(name, np.float64) for name in record.aux_names]
        )
        data = np.fromfile(self._file, dtype=dtype, count=record.nlist)
        return data.view(np.recarray)

    def _scan(self) -> list[CbcRecord]:
        f = self._file
        f.seek(0, 2)
        total_bytes = f.tell()
        f.seek(0)
        records: list[CbcRecord] = []
        while f.tell() < total_bytes:
            head = f.read(_HEADER1.size + _HEADER2.size)
            if len(head) < _HEADER1.size + _HEADER2.size:
                raise ValueError(f"truncated budget record header in {f.name}")
            kstp, kper, raw_text, ndim1, ndim2, ndim3 = _HEADER1.unpack_from(head)
            imeth, _delt, _pertim, _totim = _HEADER2.unpack_from(head, _HEADER1.size)
            if ndim3 >= 0 or not _is_printable_ascii(raw_text):
                raise ValueError(
                    f"{f.name} is not a double-precision MODFLOW 6 compact budget file"
                )
            text = raw_text.decode("ascii").strip()
            nlist = 0
            aux_names: tuple[str, ...] = ()
            if imeth == 1:
                data_pos = f.tell()
                f.seek(_REAL_BYTES * ndim1 * ndim2 * abs(ndim3), 1)
            elif imeth == 6:
                f.seek(_NAMES_BLOCK, 1)
                ndat = _read_int32(f)
                if ndat > 1:
                    aux_names = tuple(f.read(16).decode("ascii").strip() for _ in range(ndat - 1))
                nlist = _read_int32(f)
                data_pos = f.tell()
                f.seek(nlist * (8 + _REAL_BYTES * ndat), 1)
            else:
                raise ValueError(f"unsupported imeth {imeth} for record '{text}' in {f.name}")
            records.append(
                CbcRecord(
                    kstp=kstp,
                    kper=kper,
                    text=text,
                    imeth=imeth,
                    ndim1=ndim1,
                    ndim2=ndim2,
                    ndim3=ndim3,
                    nlist=nlist,
                    aux_names=aux_names,
                    data_pos=data_pos,
                )
            )
        return records


def _read_int32(f) -> int:
    return int.from_bytes(f.read(4), "little", signed=True)


def _is_printable_ascii(raw: bytes) -> bool:
    return all(32 <= byte <= 126 for byte in raw)
