"""The three environment options on the commands that compute, and what they build.

``--credentials``, ``--allow-host`` and ``--max-download-bytes`` are
registered by ``run``, ``replay``, ``calibrate``, ``spinup``, ``export``, ``data get``
and ``campaign array`` alone. The command builds one
:class:`~hydromodpy.project.environment.Environment` from them and hands it
to the verb it wraps; the launcher serializes the same Environment onto the
command line of a case, the worker of the case being ``hmp run`` again.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.cli.environment import environment_flags_of, environment_from_args
from hydromodpy.core.runtime.bounds import DEFAULT_MAX_DOWNLOAD_BYTES, Bounds
from hydromodpy.project.environment import Environment
from hydromodpy.project.launch.children import PlannedCase, worker_command
from tests.unit.cli._hmp import run_hmp
from tests.unit.cli._tree import leaves

ENVIRONMENT_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("run",),
    ("replay",),
    ("calibrate",),
    ("spinup",),
    ("export",),
    ("data", "get"),
    ("campaign", "array"),
)


def _arguments(**values: object) -> SimpleNamespace:
    """Return the argparse namespace the three options produce, with the defaults."""
    space = SimpleNamespace(credentials=None, allow_host=[], max_download_bytes=None)
    for key, value in values.items():
        setattr(space, key, value)
    return space


@pytest.mark.parametrize("words", ENVIRONMENT_COMMANDS)
def test_the_commands_that_compute_carry_the_three_options(words: tuple[str, ...]) -> None:
    parser = dict(leaves()).get(words)
    assert parser is not None, f"{words} is not a command of the tree"
    names = {action.dest for action in parser._actions}
    assert {"credentials", "allow_host", "max_download_bytes"} <= names


def test_no_other_command_carries_the_options() -> None:
    computing = set(ENVIRONMENT_COMMANDS)
    for words, parser in leaves():
        names = {action.dest for action in parser._actions}
        has = {"credentials", "allow_host", "max_download_bytes"} <= names
        if words in computing:
            assert has, f"{words} does not register the environment options"
        else:
            assert not has, f"{words} registers options the lot did not announce"


def test_the_absent_options_read_into_the_default_environment() -> None:
    environment = environment_from_args(_arguments())

    assert environment.credentials is not None
    assert environment.credentials.name == "credentials.toml"
    assert environment.bounds.allowed_hosts is None
    assert environment.bounds.max_download_bytes == DEFAULT_MAX_DOWNLOAD_BYTES


def test_a_named_credentials_file_and_a_ceiling_read_through() -> None:
    environment = environment_from_args(
        _arguments(credentials="/srv/keys/fuel.toml", max_download_bytes=1024)
    )

    assert str(environment.credentials) == "/srv/keys/fuel.toml"
    assert environment.bounds.max_download_bytes == 1024


@pytest.mark.parametrize(
    ("hosts", "stored"),
    [
        (["Data.GEOPF.fr:443"], {"data.geopf.fr"}),
        (["a.org", "b.org", "a.org"], {"a.org", "b.org"}),
        ([], None),
    ],
)
def test_allow_host_repeats_and_the_port_is_dropped(
    hosts: list[str], stored: set[str] | None
) -> None:
    environment = environment_from_args(_arguments(allow_host=hosts))

    assert environment.bounds.allowed_hosts == (None if stored is None else frozenset(stored))


@pytest.mark.parametrize("ceiling", [0, -1])
def test_a_ceiling_of_zero_or_less_refuses_in_code_2(
    ceiling: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = run_hmp(monkeypatch, "run", "no-such-file.toml", "--max-download-bytes", str(ceiling))

    assert code == 2


def test_a_negative_ceiling_refuses_the_command_outside_a_parser() -> None:
    with pytest.raises(SystemExit) as raised:
        environment_from_args(_arguments(max_download_bytes=-5))

    assert raised.value.code == 2


def test_the_flags_of_the_named_options() -> None:
    flags = environment_flags_of(
        _arguments(credentials="/srv/keys/fuel.toml", allow_host=["a.org"], max_download_bytes=2048)
    )

    assert flags == (
        "--credentials",
        "/srv/keys/fuel.toml",
        "--allow-host",
        "a.org",
        "--max-download-bytes",
        "2048",
    )


def test_a_relative_credentials_path_crosses_resolved() -> None:
    flags = environment_flags_of(_arguments(credentials="keys/fuel.toml"))

    assert flags[0] == "--credentials"
    assert flags[1] == str(Path("keys/fuel.toml").resolve())
    assert Path(flags[1]).is_absolute()


def test_the_worker_runs_from_elsewhere_and_reads_the_same_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    environment = environment_from_args(_arguments(credentials="keys/fuel.toml"))

    assert environment.credentials == Path("keys/fuel.toml").resolve()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    rebuilt = environment_from_args(_arguments(credentials=str(environment.credentials)))
    assert rebuilt.credentials == environment.credentials


def test_no_named_option_gives_no_flag() -> None:
    assert environment_flags_of(_arguments()) == ()


def test_the_flags_rebuild_the_named_environment() -> None:
    flags = environment_flags_of(
        _arguments(credentials="/srv/keys/fuel.toml", allow_host=["a.org"], max_download_bytes=2048)
    )
    namespace = _arguments()
    for position in range(0, len(flags), 2):
        option, value = flags[position], flags[position + 1]
        if option == "--credentials":
            namespace.credentials = value
        elif option == "--allow-host":
            namespace.allow_host = [*namespace.allow_host, value]
        else:
            namespace.max_download_bytes = int(value)

    environment = environment_from_args(namespace)

    assert str(environment.credentials) == "/srv/keys/fuel.toml"
    assert environment.bounds.allowed_hosts == frozenset({"a.org"})
    assert environment.bounds.max_download_bytes == 2048


def test_a_case_line_carries_the_options_after_the_attempt_flags() -> None:
    case = PlannedCase(
        case_id="a-base",
        site="a",
        recipe="base",
        config_hash="0",
        path=Path("plan/ab/a-base.toml"),
        workflow="simulation",
        solves=1,
    )
    flags = environment_flags_of(
        _arguments(credentials="/srv/keys/fuel.toml", allow_host=["a.org"], max_download_bytes=2048)
    )

    command = worker_command(case, ["--frozen"], environment_flags=flags)

    assert command[1:4] == ["-m", "hydromodpy", "run"]
    assert command[4] == "plan/ab/a-base.toml"
    assert command[5:] == [
        "--frozen",
        "--credentials",
        "/srv/keys/fuel.toml",
        "--allow-host",
        "a.org",
        "--max-download-bytes",
        "2048",
    ]
