"""The solver layering tables move to ``[domain.layers]``, on load and in a file."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
import tomlkit

from hydromodpy.config.config_migration import fix_config_file, migrate_config_doc

_MF6 = '[modflow6.sgrid.vertical]\ngenmtd_lay = "decay"\nnlay = 10\nlay_decay = 1.2\n'
_NWT = '[modflownwt.sgrid.vertical]\ngenmtd_lay = "constant"\nnlay = 3\n'


def _flow_process(solver: str) -> str:
    return f'[[simulation.process]]\nid = "flow"\ntype = "flow"\nsolvers = ["{solver}"]\n'


def test_one_solver_table_becomes_domain_layers_and_leaves_no_empty_header(
    tmp_path: Path,
) -> None:
    path = tmp_path / "project.toml"
    path.write_text("[domain.depth_model]\nthickness = 30\n\n" + _MF6, encoding="utf-8")

    changes = fix_config_file(path)

    assert changes == ["modflow6.sgrid.vertical -> [domain.layers]"]
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["domain"]["layers"] == {"genmtd_lay": "decay", "nlay": 10, "lay_decay": 1.2}
    assert parsed["domain"]["depth_model"] == {"thickness": 30}
    assert "modflow6" not in parsed


def test_a_nwt_table_alone_moves_and_keeps_the_other_solver_keys() -> None:
    doc = tomllib.loads(_NWT + '\n[modflownwt.sgrid.top_sampling]\nmode = "zonal"\n')

    changes = migrate_config_doc(doc)

    assert "modflownwt.sgrid.vertical -> [domain.layers]" in changes
    assert doc["domain"]["layers"] == {"genmtd_lay": "constant", "nlay": 3}
    assert doc["modflownwt"]["sgrid"] == {"top_sampling": {"mode": "zonal"}}


def test_two_equal_tables_keep_one_and_say_the_dropped_one_held_the_same_values() -> None:
    doc = tomllib.loads(_MF6 + _MF6.replace("modflow6", "modflownwt"))

    changes = migrate_config_doc(doc)

    assert "modflow6.sgrid.vertical -> [domain.layers]" in changes
    assert "modflownwt.sgrid.vertical dropped (modflow6 is the flow solver; same values)" in changes
    assert doc["domain"]["layers"]["nlay"] == 10


@pytest.mark.parametrize(
    ("solver", "kept", "nlay"),
    [
        ("modflow6", "modflow6", 10),
        ("modflow6_prt", "modflow6", 10),
        ("modflow_nwt", "modflownwt", 3),
        ("boussinesq", "modflow6", 10),
    ],
)
def test_two_different_tables_keep_the_layering_of_the_flow_process_solver(
    solver: str, kept: str, nlay: int
) -> None:
    doc = tomllib.loads(_flow_process(solver) + _MF6 + _NWT)

    changes = migrate_config_doc(doc)

    dropped = "modflownwt" if kept == "modflow6" else "modflow6"
    assert f"{kept}.sgrid.vertical -> [domain.layers]" in changes
    line = next(change for change in changes if change.startswith(f"{dropped}.sgrid.vertical"))
    assert f"{kept} is the flow solver; it held other values:" in line
    assert "nlay = " in line
    assert doc["domain"]["layers"]["nlay"] == nlay
    assert "modflow6" not in doc
    assert "modflownwt" not in doc


@pytest.mark.parametrize(
    ("backend", "nlay"),
    [
        ('{ backend = "modflow_nwt" }', 3),
        ('{ backend = "modflow6" }', 10),
        ('{ backend = "custom", name = "modflow_nwt" }', 3),
    ],
)
def test_without_a_flow_process_the_solver_backend_picks_the_layering(
    backend: str, nlay: int
) -> None:
    doc = tomllib.loads(f"[solver]\nbackend = {backend}\n\n" + _MF6 + _NWT)

    migrate_config_doc(doc)

    assert doc["domain"]["layers"]["nlay"] == nlay


def test_without_a_flow_solver_the_layering_of_modflow6_is_kept() -> None:
    doc = tomllib.loads(_NWT + _MF6)

    migrate_config_doc(doc)

    assert doc["domain"]["layers"]["nlay"] == 10


def test_an_existing_domain_layers_wins_and_both_solver_tables_drop() -> None:
    doc = tomllib.loads("[domain.layers]\nnlay = 3\n" + _MF6 + _NWT)

    changes = migrate_config_doc(doc)

    assert doc["domain"]["layers"] == {"nlay": 3}
    assert (
        "modflownwt.sgrid.vertical dropped ([domain.layers] already set; it held other "
        "values: genmtd_lay = 'constant' against unset)"
    ) in changes
    mf6 = next(change for change in changes if change.startswith("modflow6.sgrid.vertical"))
    assert mf6.startswith("modflow6.sgrid.vertical dropped ([domain.layers] already set;")
    assert "nlay = 10 against 3" in mf6


def test_a_tomlkit_document_moves_the_table_with_its_comments() -> None:
    doc = tomlkit.parse(
        _flow_process("modflow_nwt") + _MF6 + _NWT.replace("nlay = 3", "nlay = 3 # thin")
    )

    changes = migrate_config_doc(doc)

    assert "modflownwt.sgrid.vertical -> [domain.layers]" in changes
    text = tomlkit.dumps(doc)
    assert "[domain.layers]" in text
    assert "nlay = 3 # thin" in text
    assert "sgrid" not in text


def _phase(overrides: str) -> str:
    return f'[[calibration.phases]]\nname = "deep"\n\n[calibration.phases.overrides]\n{overrides}\n'


def test_a_dotted_phase_override_moves_to_domain_layers() -> None:
    doc = tomllib.loads(_phase('"modflownwt.sgrid.vertical.nlay" = 3'))

    changes = migrate_config_doc(doc)

    assert changes == [
        'calibration.phases[0].overrides."modflownwt.sgrid.vertical.nlay" -> "domain.layers.nlay"'
    ]
    assert doc["calibration"]["phases"][0]["overrides"] == {"domain.layers.nlay": 3}


def test_a_phase_writing_both_solvers_keeps_the_flow_solver_paths() -> None:
    doc = tomllib.loads(
        _flow_process("modflow_nwt")
        + _phase('"modflow6.sgrid.vertical.nlay" = 10\n"modflownwt.sgrid.vertical.nlay" = 3')
    )

    changes = migrate_config_doc(doc)

    assert doc["calibration"]["phases"][0]["overrides"] == {"domain.layers.nlay": 3}
    assert (
        'calibration.phases[0].overrides."modflow6.sgrid.vertical.nlay" dropped '
        "(modflownwt is the flow solver)"
    ) in changes


def test_a_phase_override_already_on_domain_layers_is_left() -> None:
    doc = tomllib.loads(_phase('"domain.layers.nlay" = 2\n"modflow6.sgrid.vertical.nlay" = 3'))

    changes = migrate_config_doc(doc)

    assert changes == [
        'calibration.phases[0].overrides."modflow6.sgrid.vertical.nlay" left: '
        '"domain.layers.nlay" is given too, keep one'
    ]


def test_a_dotted_phase_override_moves_in_a_file_with_its_comment(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(_phase('"modflow6.sgrid.vertical.nlay" = 3 # deeper'), encoding="utf-8")

    fix_config_file(path)

    text = path.read_text(encoding="utf-8")
    assert '"domain.layers.nlay" = 3 # deeper' in text
    assert "sgrid" not in text


def test_a_config_without_solver_layering_is_untouched() -> None:
    doc = tomllib.loads(
        '[domain.layers]\nnlay = 2\n\n[modflow6.sgrid.top_sampling]\nmode = "zonal"\n'
    )

    assert migrate_config_doc(doc) == []
    assert doc["modflow6"]["sgrid"]["top_sampling"] == {"mode": "zonal"}
