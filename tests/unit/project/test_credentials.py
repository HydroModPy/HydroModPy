"""The reader of ``credentials.toml``, and the word it places on its table.

Twelve refusals, each with its sentence: where the file may not live, how it
must be readable, and what a ``[[host]]`` block may carry for its scheme.
The same refusals are the ones ``Environment.check`` places at the open of a
project, so a refused file stops a verb before its first step.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG, exit_code_for
from hydromodpy.core.exceptions import CredentialsError
from hydromodpy.project.credentials import HostCredential, credential_for, load_credentials

GOOD_PREFIX = "ftps://depot.example.org/hydromodpy/"
KEY = """prefix = "ftps://depot.example.org/hydromodpy/"
user = "bastien"
password = "s3cr3t-hunter2"
"""


def _write(root: Path, body: str, name: str = "credentials.toml", mode: int = 0o600) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(mode)
    return path


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A folder that is neither a project nor a workspace."""
    folder = tmp_path / "home"
    folder.mkdir(parents=True)
    return folder


def test_a_prefix_cuts_at_a_segment_boundary() -> None:
    """``ftp://h/a`` does not answer for ``ftp://h/ab/``."""
    credentials = (HostCredential(prefix="ftp://h/a", user="b"),)
    assert credential_for("ftp://h/ab/", credentials) is None
    assert credential_for("ftp://h/a/x", credentials) is not None


@pytest.mark.parametrize(("body", "secret"), [("s3cr3t-file\n", "s3cr3t-file"), (None, None)])
def test_secret_of_a_block(tmp_path: Path, body: str | None, secret: str | None) -> None:
    secret_file = None
    if body is not None:
        secret_file = tmp_path / "depot.secret"
        secret_file.write_text(body)
    block = HostCredential(prefix=GOOD_PREFIX, user="b", password_file=secret_file)
    assert block.secret() == secret


@pytest.mark.parametrize(
    ("body", "mode", "match"),
    [
        pytest.param('[[host]]\nuser = "b"\n', 0o600, "prefix", id="a-block-without-a-prefix"),
        pytest.param(
            f'[[host]]\nprefix = "{GOOD_PREFIX}"\npassword = "a"\npassword_file = "secret"\n',
            0o600,
            "together",
            id="password-and-a-file-together",
        ),
        pytest.param(
            '[[host]]\nprefix = "depot.example.org/hydromodpy/"\nuser = "b"\n',
            0o600,
            "carries no scheme",
            id="a-prefix-without-a-scheme",
        ),
        pytest.param(
            '[[host]]\nprefix = "file:///data/raster.tif"\nuser = "b"\n',
            0o600,
            "ftp, ftps, sftp, http or https",
            id="a-prefix-of-another-scheme",
        ),
        pytest.param(
            '[[host]]\nprefix = "https://depot.example.org/"\nkey_file = "id"\n',
            0o600,
            "only an sftp:// prefix serves",
            id="a-key-file-outside-sftp",
        ),
        pytest.param(
            '[[host]]\nprefix = "https://depot.example.org/"\nhost_fingerprint = "SHA256:AB"\n',
            0o600,
            "only an sftp:// prefix serves",
            id="a-fingerprint-outside-sftp",
        ),
        pytest.param(
            f'[[host]]\nprefix = "{GOOD_PREFIX}"\nuser = "b"\norganisation = "nope"\n',
            0o600,
            "organisation",
            id="an-unknown-key",
        ),
        pytest.param(
            f'[[host]]\nprefix = "{GOOD_PREFIX}"\nuser = "b"\npassword = "a"\n\n'
            f'[[host]]\nprefix = "{GOOD_PREFIX}"\nuser = "c"\npassword = "b"\n',
            0o600,
            "same prefix",
            id="two-blocks-at-one-prefix",
        ),
    ],
)
def test_a_file_a_block_refuses(outside: Path, body: str, mode: int, match: str) -> None:
    path = _write(outside, body, mode=mode)
    with pytest.raises(CredentialsError, match=match):
        load_credentials(path, forbidden_roots=(outside / "project", outside / "space"))


def test_a_file_named_and_absent_is_refused_with_the_code_of_a_configuration(
    outside: Path,
) -> None:
    with pytest.raises(CredentialsError) as raised:
        load_credentials(outside / "absent.toml")
    message = str(raised.value)
    assert "does not exist" in message and "absent.toml" in message
    assert not isinstance(raised.value, FileNotFoundError)
    assert exit_code_for(raised.value) == EXIT_CONFIG == 14


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_a_file_under_a_project_or_a_workspace_is_refused(
    outside: Path,
) -> None:
    body = f"[[host]]\n{KEY}"
    for parent in ("project", "space"):
        folder = outside / parent
        folder.mkdir(parents=True)
        path = _write(folder, body, mode=0o600)
        with pytest.raises(CredentialsError, match="outside every project and workspace"):
            load_credentials(path, forbidden_roots=(outside / "project", outside / "space"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_a_file_readable_beyond_its_owner_is_refused(
    outside: Path,
) -> None:
    path = _write(outside, f"[[host]]\n{KEY}", mode=0o644)
    with pytest.raises(CredentialsError, match="chmod 600"):
        load_credentials(path, forbidden_roots=())


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_a_password_file_readable_by_others_is_refused(
    outside: Path,
) -> None:
    secret = _write(outside, "s3cr3t\n", name="depot.secret", mode=0o644)
    body = f'[[host]]\nprefix = "{GOOD_PREFIX}"\nuser = "b"\npassword_file = "{secret}"\n'
    path = _write(outside, body)
    with pytest.raises(CredentialsError, match="chmod 600"):
        load_credentials(path, forbidden_roots=())


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_a_password_file_named_and_absent_is_refused(
    outside: Path,
) -> None:
    body = (
        f'[[host]]\nprefix = "{GOOD_PREFIX}"\nuser = "b"\n'
        f'password_file = "{outside / "no.secret"}"\n'
    )
    path = _write(outside, body)
    with pytest.raises(CredentialsError, match="no.secret"):
        load_credentials(path, forbidden_roots=())


def test_a_file_that_is_not_toml_is_refused_with_its_line(
    outside: Path,
) -> None:
    path = _write(outside, "[[host]]\nprefix = \n")
    with pytest.raises(CredentialsError, match="not a valid TOML file") as raised:
        load_credentials(path, forbidden_roots=())
    assert "line 2" in str(raised.value)
