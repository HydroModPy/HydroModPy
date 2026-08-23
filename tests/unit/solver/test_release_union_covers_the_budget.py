"""The union of release packages must cover what the budget file actually holds.

The declaration comes from the model object, and a model object can be silent
about a package the run really built. Measured on the Nancon with the streams in
SFR: the aquifer sent 1.33 of its 2.10 m3/s through the stream package while the
union read the 0.80 of the drain alone, and nothing said so. The criterion then
measured a seepage network missing two thirds of its water, the simulated
network stopped retracting, and the search closed three decades outside its
declared bounds on a value that means nothing.
"""

from __future__ import annotations

import pytest

from hydromodpy.solver.modflow_common.calibration_extractors import (
    ReleasePackage,
    _refuse_records_the_union_misses,
)

DRN = ReleasePackage(name="DRN", record_aliases=("DRN", "DRAIN", "DRAINS"))
SFR = ReleasePackage(name="SFR", record_aliases=("SFR",))


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


class TestSiblingBudgets:
    """A package whose budget goes to its own file must not read as absent.

    MODFLOW 6 sends an advanced package's budget to ``<stem>.<pkg>.cbc`` when it
    is given a ``budget_filerecord``. The model CBC then holds no record for it,
    and a union built by reading that file alone reports the package as absent
    rather than as unread.
    """

    def test_a_stream_budget_beside_the_model_one_is_refused(self, tmp_path) -> None:
        from hydromodpy.solver.modflow_common.calibration_extractors import (
            _refuse_sibling_budgets_the_union_cannot_read,
        )

        cbc = tmp_path / "nancon.cbc"
        cbc.write_bytes(b"")
        (tmp_path / "nancon.sfr.cbc").write_bytes(b"")

        with pytest.raises(KeyError, match="SFR"):
            _refuse_sibling_budgets_the_union_cannot_read(cbc, [DRN])

    def test_a_package_already_in_the_union_is_not_refused(self, tmp_path) -> None:
        from hydromodpy.solver.modflow_common.calibration_extractors import (
            _refuse_sibling_budgets_the_union_cannot_read,
        )

        cbc = tmp_path / "nancon.cbc"
        cbc.write_bytes(b"")
        (tmp_path / "nancon.sfr.cbc").write_bytes(b"")

        _refuse_sibling_budgets_the_union_cannot_read(cbc, [DRN, SFR])

    def test_no_sibling_means_nothing_to_refuse(self, tmp_path) -> None:
        from hydromodpy.solver.modflow_common.calibration_extractors import (
            _refuse_sibling_budgets_the_union_cannot_read,
        )

        cbc = tmp_path / "nancon.cbc"
        cbc.write_bytes(b"")

        _refuse_sibling_budgets_the_union_cannot_read(cbc, [DRN])

    def test_the_message_says_where_the_water_would_be_lost(self, tmp_path) -> None:
        from hydromodpy.solver.modflow_common.calibration_extractors import (
            _refuse_sibling_budgets_the_union_cannot_read,
        )

        cbc = tmp_path / "nancon.cbc"
        cbc.write_bytes(b"")
        (tmp_path / "nancon.lak.cbc").write_bytes(b"")

        with pytest.raises(KeyError) as failure:
            _refuse_sibling_budgets_the_union_cannot_read(cbc, [DRN])

        assert "dry land" in str(failure.value)
        assert "LAK" in str(failure.value)
