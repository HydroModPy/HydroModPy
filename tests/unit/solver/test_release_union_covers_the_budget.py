"""The union of release packages must cover what the budget file actually holds.

Two guards share that job and they answer different questions. One reads the
records the model budget holds and refuses any release record no declared
package reads. The other looks for a package budget written to its own file
next to the model one, and refuses only when the model budget is silent about
that package, which is the only case the union genuinely cannot see.

The second guard used to refuse on the mere presence of the sibling file. That
premise does not hold: ``budget_filerecord`` and ``save_flows`` are independent
MODFLOW 6 options and the builders here set both, so the per-cell exchange is in
the model budget as well. The end-to-end tests below run the union over a budget
holding a stream record and show it reading exactly the water the aquifer loses.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow_common.calibration_extractors import (
    ReleasePackage,
    _refuse_records_the_union_misses,
    _refuse_sibling_budgets_the_union_cannot_read,
    extract_release_flux_by_cell_from_cbc,
)

DRN = ReleasePackage(name="DRN", record_aliases=("DRN", "DRAIN", "DRAINS"))
SFR = ReleasePackage(name="SFR", record_aliases=("SFR",))

_N_CELLS = 6
_N_LAY = 1


def test_a_union_that_covers_every_release_record_passes() -> None:
    _refuse_records_the_union_misses(
        [DRN, SFR],
        ["         DRN", "         SFR", "         STO-SS", "       RECHARGE"],
    )


def test_a_stream_record_no_package_reads_is_refused() -> None:
    with pytest.raises(KeyError, match="SFR"):
        _refuse_records_the_union_misses([DRN], ["         DRN", "         SFR"])


def test_the_message_names_what_is_missed_and_what_is_covered() -> None:
    with pytest.raises(KeyError) as failure:
        _refuse_records_the_union_misses([DRN], ["         DRN", "         LAK"])

    message = str(failure.value)
    assert "LAK" in message
    assert "DRAIN" in message
    assert "dry land" in message


def test_records_that_do_not_release_are_ignored() -> None:
    # Storage and recharge are not a path out of the aquifer to the surface.
    _refuse_records_the_union_misses(
        [DRN],
        ["         DRN", "         STO-SY", "       RECHARGE", "FLOW-JA-FACE"],
    )


def test_the_comparison_ignores_the_padding_flopy_keeps() -> None:
    # FloPy stores record names padded to a fixed width; a naive comparison
    # would miss every one of them.
    _refuse_records_the_union_misses([DRN, SFR], ["  DRN   ", "\tSFR\n"])


@pytest.mark.parametrize("record", ["CHD", "CONSTANT HEAD", "RIV", "UZF", "DRN-TO-MVR"])
def test_every_declared_release_path_is_watched(record: str) -> None:
    with pytest.raises(KeyError, match="release record"):
        _refuse_records_the_union_misses([DRN], ["         DRN", f"         {record}"])


def test_a_package_declared_but_absent_from_the_file_is_not_this_guard_s_business() -> None:
    # That case belongs to _resolve_release_record, which refuses it by name.
    _refuse_records_the_union_misses([DRN, SFR], ["         DRN"])


class TestRecordsTheModelRuledOut:
    """Declaring an exclusion is not the same as forgetting one.

    Every MODFLOW-NWT catchment closes on a lateral constant head, so a guard
    that refuses on the mere presence of a ``CONSTANT HEAD`` record refuses the
    normal case. What separates the two is whether the model LOOKED at the
    package and gave a reason.
    """

    LATERAL_CHD = {
        "CHD": "no cell of it carries the stream role",
        "CONSTANT HEAD": "no cell of it carries the stream role",
    }

    def test_a_lateral_constant_head_the_model_ruled_out_is_not_refused(self) -> None:
        _refuse_records_the_union_misses(
            [DRN],
            ["         DRN", "  CONSTANT HEAD"],
            excluded_records=self.LATERAL_CHD,
        )

    def test_the_same_record_with_no_reason_is_still_refused(self) -> None:
        with pytest.raises(KeyError, match="CONSTANT HEAD"):
            _refuse_records_the_union_misses([DRN], ["         DRN", "  CONSTANT HEAD"])

    def test_an_exclusion_does_not_cover_a_different_record(self) -> None:
        with pytest.raises(KeyError, match="SFR"):
            _refuse_records_the_union_misses(
                [DRN],
                ["         DRN", "  CONSTANT HEAD", "         SFR"],
                excluded_records=self.LATERAL_CHD,
            )

    def test_the_exclusion_is_announced_with_its_reason(self, caplog) -> None:
        with caplog.at_level("INFO"):
            _refuse_records_the_union_misses(
                [DRN],
                ["         DRN", "  CONSTANT HEAD"],
                excluded_records=self.LATERAL_CHD,
            )
        assert "CONSTANT HEAD" in caplog.text
        assert "stream role" in caplog.text

    def test_a_stream_constant_head_stays_in_the_union(self) -> None:
        # The model declared it, so it is read rather than ruled out, and the
        # guard has nothing to say either way.
        stream_chd = ReleasePackage(name="CHD", record_aliases=("CHD", "CONSTANT HEAD"))
        _refuse_records_the_union_misses(
            [DRN, stream_chd], ["         DRN", "  CONSTANT HEAD"], excluded_records={}
        )


class TestTheModelDeclaresWhatItLeavesOut:
    """The reason has to come from the model, not from the reader."""

    def test_a_run_whose_constant_head_holds_no_stream_rules_it_out(self) -> None:
        from types import SimpleNamespace

        from hydromodpy.solver.modflow_common.observable_extraction import (
            excluded_release_records_for_model,
        )

        model = SimpleNamespace(chd=object(), drn=object())
        excluded = excluded_release_records_for_model(model)
        assert set(excluded) == {"CHD", "CONSTANT HEAD"}
        assert "stream role" in excluded["CHD"]

    def test_a_backend_that_exposes_no_chd_attribute_still_rules_it_out(self) -> None:
        # MODFLOW-NWT builds its lateral boundary without a `chd` attribute on
        # the model. Keying the exclusion on that attribute ruled nothing out
        # and refused every NWT catchment for closing on a boundary.
        from types import SimpleNamespace

        from hydromodpy.solver.modflow_common.observable_extraction import (
            excluded_release_records_for_model,
        )

        assert set(excluded_release_records_for_model(SimpleNamespace(drn=object()))) == {
            "CHD",
            "CONSTANT HEAD",
        }

    def test_a_constant_head_carrying_the_stream_role_is_not_ruled_out(self) -> None:
        from types import SimpleNamespace

        from hydromodpy.solver.modflow_common.observable_extraction import (
            excluded_release_records_for_model,
        )

        model = SimpleNamespace(
            chd=object(),
            drn=object(),
            _stream_support_mask=np.array([False, True, False]),
        )
        assert excluded_release_records_for_model(model) == {}


class TestSiblingBudgets:
    """A sibling package budget only matters when the model budget is silent.

    MODFLOW 6 sends an advanced package budget to ``<stem>.<pkg>.cbc`` when it is
    given a ``budget_filerecord``, and it also writes that package per-cell
    exchange into the model budget when the package carries ``save_flows``. The
    two options are independent, so the presence of the sibling file says
    nothing about what the model budget holds.
    """

    def test_a_stream_budget_the_model_one_says_nothing_about_is_refused(self, tmp_path) -> None:
        cbc = tmp_path / "nancon.cbc"
        cbc.write_bytes(b"")
        (tmp_path / "nancon.sfr.cbc").write_bytes(b"")

        with pytest.raises(KeyError, match="SFR"):
            _refuse_sibling_budgets_the_union_cannot_read(cbc, [DRN], ["         DRN"])

    def test_a_package_already_in_the_union_is_not_refused(self, tmp_path) -> None:
        cbc = tmp_path / "nancon.cbc"
        cbc.write_bytes(b"")
        (tmp_path / "nancon.sfr.cbc").write_bytes(b"")

        _refuse_sibling_budgets_the_union_cannot_read(
            cbc, [DRN, SFR], ["         DRN", "         SFR"]
        )

    def test_a_record_the_model_budget_holds_is_left_to_the_other_guard(self, tmp_path) -> None:
        # The union does not read LAK, so this run must still be refused; but the
        # refusal has to come from the guard that reads the records, with the
        # message that names them, not from a file listing beside the budget.
        cbc = tmp_path / "cheze.cbc"
        cbc.write_bytes(b"")
        (tmp_path / "cheze.lak.cbc").write_bytes(b"")

        _refuse_sibling_budgets_the_union_cannot_read(cbc, [DRN], ["         DRN", "         LAK"])
        with pytest.raises(KeyError, match="LAK"):
            _refuse_records_the_union_misses([DRN], ["         DRN", "         LAK"])

    def test_no_sibling_means_nothing_to_refuse(self, tmp_path) -> None:
        cbc = tmp_path / "nancon.cbc"
        cbc.write_bytes(b"")

        _refuse_sibling_budgets_the_union_cannot_read(cbc, [DRN], ["         DRN"])

    def test_the_message_says_where_the_water_would_be_lost(self, tmp_path) -> None:
        cbc = tmp_path / "nancon.cbc"
        cbc.write_bytes(b"")
        (tmp_path / "nancon.lak.cbc").write_bytes(b"")

        with pytest.raises(KeyError) as failure:
            _refuse_sibling_budgets_the_union_cannot_read(cbc, [DRN], ["         DRN"])

        assert "dry land" in str(failure.value)
        assert "LAK" in str(failure.value)


def _list_record(text: str, rows: list[tuple[int, int, float]]) -> bytes:
    """One IMETH 6 budget record, in the layout MODFLOW 6 writes it.

    ``rows`` are ``(node, node2, q)`` with 1-based node numbers and ``q`` signed
    from the aquifer point of view, as MODFLOW 6 stores every model budget.
    """
    head = struct.pack("<2i16s3i", 1, 1, text.rjust(16).encode(), _N_CELLS, 1, -_N_LAY)
    head += struct.pack("<i3d", 6, 1.0, 1.0, 1.0)
    for name in ("GWF_1", text.strip(), "GWF_1", text.strip()):
        head += name.ljust(16).encode()
    head += struct.pack("<i", 1)
    head += struct.pack("<i", len(rows))
    payload = np.array(rows, dtype=np.dtype([("node", "<i4"), ("node2", "<i4"), ("q", "<f8")]))
    return head + payload.tobytes()


def _write_budget(
    directory: Path, name: str, records: dict[str, list[tuple[int, int, float]]]
) -> Path:
    """Write a one-timestep model budget holding the given list records."""
    path = directory / f"{name}.cbc"
    path.write_bytes(b"".join(_list_record(text, rows) for text, rows in records.items()))
    return path


class TestTheStreamExchangeOnTheCellSupport:
    """What the union reads off a budget holding a stream record.

    The signs are the ones MODFLOW 6 writes and they were measured, not assumed:
    on a run of the production SFR builder the model budget ``SFR`` record is
    signed from the aquifer point of view, negative where the reach gains, and
    ``<stem>.sfr.cbc`` carries the same flux per reach with the opposite sign.
    """

    def test_a_gaining_reach_releases_and_a_losing_one_releases_nothing(self, tmp_path) -> None:
        directory = tmp_path / "run"
        directory.mkdir()
        _write_budget(directory, "nancon", {"SFR": [(2, 1, 4.0), (5, 2, -3.0)]})

        frame = extract_release_flux_by_cell_from_cbc(
            directory, "nancon", packages=[SFR], n_cells=_N_CELLS
        )

        assert frame.shape == (1, _N_CELLS)
        # Cell 2 takes water in and releases nothing; cell 5 gives 3.0 up.
        assert frame.to_numpy()[0].tolist() == [0.0, 0.0, 0.0, 0.0, 3.0, 0.0]

    def test_two_reaches_on_one_cell_are_summed_before_the_clamp(self, tmp_path) -> None:
        directory = tmp_path / "run"
        directory.mkdir()
        _write_budget(
            directory,
            "nancon",
            {"SFR": [(3, 1, -2.0), (3, 2, -0.5), (4, 3, -1.0), (4, 4, 0.25)]},
        )

        released = extract_release_flux_by_cell_from_cbc(
            directory, "nancon", packages=[SFR], n_cells=_N_CELLS
        ).to_numpy()[0]

        # Two gaining reaches on cell 3 carry their total once.
        assert released[2] == pytest.approx(2.5)
        # On cell 4 a gaining and a losing reach net first: the cell is the
        # support, exactly as a drain cell nets over its own rows.
        assert released[3] == pytest.approx(0.75)

    def test_the_drain_and_the_stream_land_on_the_same_cell_index(self, tmp_path) -> None:
        directory = tmp_path / "run"
        directory.mkdir()
        _write_budget(
            directory,
            "nancon",
            {"DRN": [(1, 1, -1.0), (4, 2, -0.5)], "SFR": [(4, 1, -2.0), (6, 2, -1.5)]},
        )

        released = extract_release_flux_by_cell_from_cbc(
            directory, "nancon", packages=[DRN, SFR], n_cells=_N_CELLS
        ).to_numpy()[0]

        assert released.tolist() == [1.0, 0.0, 0.0, 2.5, 0.0, 1.5]
        assert released.sum() == pytest.approx(5.0)

    def test_the_stream_budget_beside_the_model_one_does_not_stop_the_read(self, tmp_path) -> None:
        directory = tmp_path / "run"
        directory.mkdir()
        _write_budget(directory, "nancon", {"SFR": [(2, 1, -4.0)]})
        (directory / "nancon.sfr.cbc").write_bytes(b"")

        released = extract_release_flux_by_cell_from_cbc(
            directory, "nancon", packages=[SFR], n_cells=_N_CELLS
        ).to_numpy()[0]

        assert released[1] == pytest.approx(4.0)

    def test_a_stream_record_the_union_does_not_declare_is_still_refused(self, tmp_path) -> None:
        directory = tmp_path / "run"
        directory.mkdir()
        _write_budget(directory, "nancon", {"DRN": [(1, 1, -1.0)], "SFR": [(4, 1, -2.0)]})

        with pytest.raises(KeyError, match="release record"):
            extract_release_flux_by_cell_from_cbc(
                directory, "nancon", packages=[DRN], n_cells=_N_CELLS
            )
