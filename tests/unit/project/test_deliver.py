"""The delivery of the export files of a run, to a folder or to an address.

The table of the refusals ``preflight`` places before a run computes, each with
its exit code. Then the pushes: a local folder and a local file, ``ftp``,
``ftps`` and ``sftp`` against stand-ins a test controls, the three attempts and
the ``.part`` name, the resume from ``published.jsonl``, and a password that
never reaches a line. Every call passes ``delays=(0, 0)``, so no test waits.
"""

from __future__ import annotations

import base64
import ftplib
import hashlib
import json
import logging
import os
import posixpath
import socket
import socketserver
import ssl
import sys
import types
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG, EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import (
    BoundsError,
    ConfigError,
    CredentialsError,
    ExportError,
    NetworkError,
)
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.project.credentials import HostCredential
from hydromodpy.project.deliver import (
    PART_SUFFIX,
    PROBES,
    PUSHERS,
    RETRY_DELAYS_S,
    deliver_pending,
    deliver_run,
    preflight,
)
from hydromodpy.project.environment import Environment
from hydromodpy.results.exporters.destination import (
    DELIVER_TO_KEY,
    DELIVERY_SCHEMES,
    LOCAL_SCHEME,
    parse_destination,
)
from hydromodpy.results.exporters.export_spec import ExportRequest, load_export_requests
from hydromodpy.results.exporters.request import EXPORT_PRODUCER
from hydromodpy.results.ledger import Ledger, LedgerEntry
from hydromodpy.results.publication import (
    DELIVERY_ATTEMPTS,
    PublishedLine,
    append_published,
    read_published,
)
from hydromodpy.results.storage.contract import (
    RUN_CONFIG_FILENAME,
    RUN_EXPORTS_DIRNAME,
    RUN_MANIFEST_FILENAME,
)
from tests._helpers.ftp_server import ftp_server, self_signed, server_tls

HEAD = b"head bytes of the last stress period\n"
OTHER = b"head bytes written again by a promotion\n"
SECRET = "s3cr3t-hunter2"
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
FINGERPRINT_KEY = b"the server key of the stand-in sftp server"

_UNC_PHRASE = (
    "is a UNC path, which only Windows reaches"
    if os.name != "nt"
    else "does not exist or cannot be written"
)


def _request(**fields: Any) -> ExportRequest:
    """Return the export block a test delivers, one variable by default."""
    fields.setdefault("variables", "head")
    (request,) = load_export_requests([fields])
    return request


def _options(request: ExportRequest) -> dict[str, Any]:
    """Return what the ledger records for one block: its request without the delivery."""
    return request.model_dump(mode="json", exclude_none=True, exclude={DELIVER_TO_KEY})


def _make_run(
    root: Path,
    request: ExportRequest | None,
    files: Mapping[str, bytes],
    *,
    config: str = "",
    sealed: bool = True,
) -> Path:
    """Write a run: its exports, their ledger, its configuration and its seal."""
    run_dir = root / "runs" / "run1"
    exports = run_dir / RUN_EXPORTS_DIRNAME
    exports.mkdir(parents=True)
    entries = []
    for name, payload in files.items():
        target = exports / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        if request is not None:
            entries.append(
                LedgerEntry(
                    file=name,
                    producer=EXPORT_PRODUCER,
                    options=_options(request),
                    hydromodpy_version="2.1.0",
                    at=NOW,
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
    if request is not None:
        Ledger(entries=entries).write(exports)
    (run_dir / RUN_CONFIG_FILENAME).write_text(config, encoding="utf-8")
    if sealed:
        (run_dir / RUN_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
    return run_dir


def _config_of(*destinations: str) -> str:
    """Return one ``[[export]]`` block delivering ``variables = "head"`` to *destinations*."""
    quoted = ", ".join(json.dumps(text) for text in destinations)
    return f'[[export]]\nvariables = "head"\ndeliver_to = [{quoted}]\n'


def _credentials(root: Path, body: str) -> Path:
    """Write a private ``credentials.toml`` outside the project and return its path."""
    folder = root / "home"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "credentials.toml"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o600)
    return path


def _ftp_credentials(root: Path, prefix: str, *, user: str = "user") -> Path:
    """Write the block of one ftp prefix, with the login of the test server."""
    return _credentials(
        root,
        f'[[host]]\nprefix = "{prefix}"\nuser = "{user}"\npassword = "secret"\n',
    )


def _sftp_credentials(root: Path, fingerprint: str) -> Path:
    """Write the block of an sftp prefix with the fingerprint the server shows."""
    return _credentials(
        root,
        '[[host]]\nprefix = "sftp://127.0.0.1/"\nuser = "user"\n'
        f'password = "{SECRET}"\nhost_fingerprint = "SHA256:{fingerprint}"\n',
    )


def _project(root: Path) -> Path:
    """Return the project root a delivery sits outside of."""
    project = root / "project"
    project.mkdir()
    return project


def _fingerprint_of(key: bytes) -> str:
    """Return the SHA256 fingerprint of a server key, without padding."""
    return base64.b64encode(hashlib.sha256(key).digest()).decode("ascii").rstrip("=")


def _delivery_line(
    file: str,
    destination: str,
    payload: bytes,
    state: str,
    *,
    attempts: int,
    error: str | None = None,
) -> PublishedLine:
    """Return one delivery line of a file holding *payload*."""
    return PublishedLine(
        kind="delivery",
        published_at=NOW,
        file=file,
        destination=destination,
        state=state,
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        attempts=attempts,
        error=error,
    )


def _states(run_dir: Path) -> list[str]:
    """Return the states of the delivery lines of a run, in file order."""
    return [line.state or "" for line in read_published(run_dir) if line.kind == "delivery"]


def _no_parts(root: Path) -> bool:
    """Answer whether no ``.part`` name is left anywhere under *root*."""
    return list(root.rglob("*" + PART_SUFFIX)) == []


def _sftp_root(root: Path) -> Path:
    """Return the server folder of the sftp stand-in, its depot created."""
    server = root / "srv"
    (server / "depot").mkdir(parents=True)
    return server


def test_registries_cover_schemes() -> None:
    schemes = set(DELIVERY_SCHEMES) | {LOCAL_SCHEME}
    assert set(PUSHERS) == schemes
    assert set(PROBES) == schemes
    assert all(callable(push) for push in PUSHERS.values())
    assert all(callable(probe) for probe in PROBES.values())


def test_delivery_constants() -> None:
    assert DELIVERY_ATTEMPTS == 3
    assert RETRY_DELAYS_S == (1.0, 2.0)
    assert PART_SUFFIX == ".part"


def _host_not_allowed(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    request = _request(deliver_to=["ftp://127.0.0.1:21/depot/"])
    environment = Environment(bounds=Bounds(allowed_hosts=frozenset({"other.example.org"})))
    return [request], environment


def _private_address_not_named(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    request = _request(deliver_to=["ftp://127.0.0.1:21/depot/"])
    return [request], Environment()


def _folder_outside_the_roots(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    request = _request(deliver_to=[str(root / "depot") + "/"])
    return [request], Environment(bounds=Bounds(allowed_roots=(project,)))


def _no_block_answers(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    credentials = _ftp_credentials(root, "ftp://127.0.0.1:1/other/")
    request = _request(deliver_to=[f"ftp://127.0.0.1:{port}/depot/"])
    environment = Environment(
        credentials=credentials, bounds=Bounds(allowed_hosts=frozenset({"127.0.0.1"}))
    )
    return [request], environment


def _no_credentials_file(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    request = _request(deliver_to=[f"ftp://127.0.0.1:{port}/depot/"])
    environment = Environment(bounds=Bounds(allowed_hosts=frozenset({"127.0.0.1"})))
    return [request], environment


def _sftp_without_fingerprint(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    credentials = _credentials(
        root, '[[host]]\nprefix = "sftp://127.0.0.1/"\nuser = "user"\npassword = "secret"\n'
    )
    request = _request(deliver_to=["sftp://127.0.0.1/depot/"])
    environment = Environment(
        credentials=credentials, bounds=Bounds(allowed_hosts=frozenset({"127.0.0.1"}))
    )
    return [request], environment


def _sftp_without_the_extra(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    credentials = _credentials(
        root,
        '[[host]]\nprefix = "sftp://127.0.0.1/"\nuser = "user"\npassword = "secret"\n'
        'host_fingerprint = "SHA256:abc"\n',
    )
    request = _request(deliver_to=["sftp://127.0.0.1/depot/"])
    environment = Environment(
        credentials=credentials, bounds=Bounds(allowed_hosts=frozenset({"127.0.0.1"}))
    )
    return [request], environment


def _unc_outside_windows(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    request = _request(deliver_to=["\\\\server\\share\\"])
    return [request], Environment()


def _local_folder_absent(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    request = _request(deliver_to=[str(root / "absent") + "/"])
    return [request], Environment()


def _server_does_not_answer(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    credentials = _ftp_credentials(root, "ftp://127.0.0.1:1/")
    request = _request(deliver_to=["ftp://127.0.0.1:1/depot/"])
    environment = Environment(
        credentials=credentials,
        bounds=Bounds(allowed_hosts=frozenset({"127.0.0.1"}), timeout_s=1.0),
    )
    return [request], environment


def _remote_folder_absent(
    root: Path, port: int, project: Path
) -> tuple[list[ExportRequest], Environment]:
    credentials = _ftp_credentials(root, f"ftp://127.0.0.1:{port}/")
    request = _request(deliver_to=[f"ftp://127.0.0.1:{port}/missing/"])
    environment = Environment(
        credentials=credentials,
        bounds=Bounds(allowed_hosts=frozenset({"127.0.0.1"}), timeout_s=2.0),
    )
    return [request], environment


@pytest.fixture
def ftp_depot(tmp_path: Path) -> Any:
    """Run the test ftp server over a root that holds one ``depot`` folder, yield its port."""
    server_root = tmp_path / "srv"
    (server_root / "depot").mkdir(parents=True)
    with ftp_server(server_root) as port:
        yield port, server_root


@pytest.mark.parametrize(
    ("build", "expected", "code", "phrase"),
    [
        pytest.param(
            _host_not_allowed,
            BoundsError,
            EXIT_CONFIG,
            "not among the hosts this call allows",
            id="host-not-allowed",
        ),
        pytest.param(
            _private_address_not_named,
            BoundsError,
            EXIT_CONFIG,
            "non-public IP address",
            id="private-address-not-named",
        ),
        pytest.param(
            _folder_outside_the_roots,
            BoundsError,
            EXIT_CONFIG,
            "outside the roots this call allows",
            id="folder-outside-the-roots",
        ),
        pytest.param(
            _no_block_answers,
            CredentialsError,
            EXIT_CONFIG,
            "no [[host]] block of",
            id="no-block-answers",
        ),
        pytest.param(
            _no_credentials_file,
            CredentialsError,
            EXIT_CONFIG,
            "this call reads no credentials file",
            id="no-credentials-file",
        ),
        pytest.param(
            _sftp_without_fingerprint,
            CredentialsError,
            EXIT_CONFIG,
            "has no host_fingerprint",
            id="sftp-without-fingerprint",
        ),
        pytest.param(
            _sftp_without_the_extra,
            ConfigError,
            EXIT_CONFIG,
            "needs the sftp extra",
            id="sftp-without-the-extra",
        ),
        pytest.param(
            _unc_outside_windows,
            ConfigError,
            EXIT_CONFIG,
            _UNC_PHRASE,
            id="unc-outside-windows",
        ),
        pytest.param(
            _local_folder_absent,
            ConfigError,
            EXIT_CONFIG,
            "does not exist or cannot be written",
            id="local-folder-absent",
        ),
        pytest.param(
            _server_does_not_answer,
            NetworkError,
            EXIT_VALIDATION,
            "does not answer",
            id="server-does-not-answer",
        ),
        pytest.param(
            _remote_folder_absent,
            NetworkError,
            EXIT_VALIDATION,
            "does not answer",
            id="remote-folder-absent",
        ),
    ],
)
def test_preflight_refusals(
    tmp_path: Path,
    ftp_depot: tuple[int, Path],
    build: Callable[[Path, int, Path], tuple[list[ExportRequest], Environment]],
    expected: type[BaseException],
    code: int,
    phrase: str,
) -> None:
    port, _root = ftp_depot
    project = _project(tmp_path)
    requests, environment = build(tmp_path, port, project)

    with pytest.raises(expected) as caught:
        preflight(requests, environment, project_root=project)

    assert phrase in str(caught.value)
    assert exit_code_for(caught.value) == code


def test_advised_prefix_has_port(tmp_path: Path, ftp_depot: tuple[int, Path]) -> None:
    port, _root = ftp_depot
    project = _project(tmp_path)
    requests, environment = _no_block_answers(tmp_path, port, project)

    with pytest.raises(CredentialsError) as caught:
        preflight(requests, environment, project_root=project)

    assert f'prefix = "ftp://127.0.0.1:{port}/"' in str(caught.value)


def test_preflight_accepts_local_targets(tmp_path: Path) -> None:
    depot = tmp_path / "depot"
    depot.mkdir()
    requests = [
        _request(deliver_to=[str(depot) + "/"]),
        _request(variables="discharge", file="one.csv", deliver_to=[str(depot / "one.csv")]),
    ]

    preflight(requests, Environment(), project_root=_project(tmp_path))


def test_clear_ftp_warns_once(
    tmp_path: Path, ftp_depot: tuple[int, Path], caplog: pytest.LogCaptureFixture
) -> None:
    port, _root = ftp_depot
    address = f"ftp://127.0.0.1:{port}/depot/"
    request = _request(deliver_to=[address])
    other = _request(variables="discharge", deliver_to=[address])
    environment = Environment(
        credentials=_ftp_credentials(tmp_path, f"ftp://127.0.0.1:{port}/"),
        bounds=Bounds(allowed_hosts=frozenset({"127.0.0.1"})),
    )

    with caplog.at_level(logging.WARNING, logger="hydromodpy.project.deliver"):
        preflight([request, other], environment, project_root=_project(tmp_path))

    told = [record for record in caplog.records if "sends its password in clear" in record.message]
    assert len(told) == 1
    assert "ftp://127.0.0.1 sends its password in clear" in told[0].message


def test_copy_to_local_folder(tmp_path: Path) -> None:
    depot = tmp_path / "depot"
    depot.mkdir()
    request = _request(deliver_to=[str(depot) + "/"])
    run_dir = _make_run(tmp_path, request, {"head/head_last.tif": HEAD})

    lines = deliver_run(
        run_dir, [request], Environment(), project_root=_project(tmp_path), delays=(0, 0)
    )

    assert len(lines) == 1
    assert _states(run_dir) == ["pending", "delivered"]
    first, last = read_published(run_dir)
    assert first.attempts == 0 and first.state == "pending"
    assert last.state == "delivered" and last.attempts == 1
    assert last.file == "exports/head/head_last.tif"
    assert last.destination == str(depot) + "/head/head_last.tif"
    assert last.sha256 == hashlib.sha256(HEAD).hexdigest()
    assert last.bytes == len(HEAD)
    assert (depot / "head" / "head_last.tif").read_bytes() == HEAD
    assert _no_parts(depot)


def test_copy_to_local_file(tmp_path: Path) -> None:
    depot = tmp_path / "depot"
    depot.mkdir()
    target = depot / "one.tif"
    request = _request(file="one.tif", deliver_to=[str(target)])
    run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD})

    lines = deliver_run(
        run_dir, [request], Environment(), project_root=_project(tmp_path), delays=(0, 0)
    )

    assert target.read_bytes() == HEAD
    assert lines[0].destination == str(target)
    assert _no_parts(depot)


@pytest.mark.skipif(os.name == "nt", reason="a POSIX symbolic link")
def test_symlink_target_is_replaced(tmp_path: Path) -> None:
    pointed = tmp_path / "elsewhere" / "kept.tif"
    pointed.parent.mkdir()
    pointed.write_bytes(b"kept")
    depot = tmp_path / "depot"
    depot.mkdir()
    target = depot / "one.tif"
    target.symlink_to(pointed)
    request = _request(file="one.tif", deliver_to=[str(target)])
    run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD})

    deliver_run(run_dir, [request], Environment(), project_root=_project(tmp_path), delays=(0, 0))

    assert not target.is_symlink()
    assert target.read_bytes() == HEAD
    assert pointed.read_bytes() == b"kept"
    assert _no_parts(depot)


def test_pairs_follow_destination_order(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    request = _request(deliver_to=[str(first) + "/", str(second) + "/"])
    run_dir = _make_run(tmp_path, request, {"a.tif": b"a", "b.tif": b"b"})

    lines = deliver_run(
        run_dir, [request], Environment(), project_root=_project(tmp_path), delays=(0, 0)
    )

    assert [(line.file, line.destination) for line in lines] == [
        ("exports/a.tif", str(first) + "/a.tif"),
        ("exports/a.tif", str(second) + "/a.tif"),
        ("exports/b.tif", str(first) + "/b.tif"),
        ("exports/b.tif", str(second) + "/b.tif"),
    ]
    assert (first / "b.tif").read_bytes() == b"b"
    assert (second / "a.tif").read_bytes() == b"a"


def test_block_without_file_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    depot = tmp_path / "depot"
    depot.mkdir()
    written = _request(deliver_to=[str(depot) + "/"])
    run_dir = _make_run(tmp_path, written, {"head_last.tif": HEAD})
    asked = _request(variables="discharge", deliver_to=[str(depot) + "/"])

    with caplog.at_level(logging.WARNING, logger="hydromodpy.project.deliver"):
        lines = deliver_run(
            run_dir, [asked], Environment(), project_root=_project(tmp_path), delays=(0, 0)
        )

    assert lines == ()
    assert "wrote no file" in caplog.text
    assert list(depot.iterdir()) == []


def test_missing_source_fails(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    depot = tmp_path / "depot"
    depot.mkdir()
    request = _request(deliver_to=[str(depot) + "/"])
    run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD})
    (run_dir / RUN_EXPORTS_DIRNAME / "head_last.tif").unlink()

    with caplog.at_level(logging.WARNING, logger="hydromodpy.project.deliver"):
        lines = deliver_run(
            run_dir, [request], Environment(), project_root=_project(tmp_path), delays=(0, 0)
        )

    assert [line.state for line in lines] == ["failed"]
    assert lines[0].attempts == 1 and lines[0].sha256 is None and lines[0].bytes is None
    assert "cannot be read" in (lines[0].error or "")
    assert "could not deliver" in caplog.text
    assert read_published(run_dir) == list(lines)
    assert list(depot.iterdir()) == []


def _ftp_environment(root: Path, port: int) -> Environment:
    """Return the environment of a delivery to the test server."""
    return Environment(
        credentials=_ftp_credentials(root, f"ftp://127.0.0.1:{port}/"),
        bounds=Bounds(allowed_hosts=frozenset({"127.0.0.1"}), timeout_s=5.0),
    )


@pytest.mark.parametrize(
    ("fail_stor", "state", "attempts"),
    [
        pytest.param(0, "delivered", 1, id="the-first-try"),
        pytest.param(2, "delivered", 3, id="two-refusals-then-delivered"),
        pytest.param(3, "failed", 3, id="three-refusals"),
    ],
)
def test_ftp_push_retries(tmp_path: Path, fail_stor: int, state: str, attempts: int) -> None:
    server_root = tmp_path / "srv"
    (server_root / "depot").mkdir(parents=True)
    with ftp_server(server_root, fail_stor=fail_stor) as port:
        request = _request(deliver_to=[f"ftp://127.0.0.1:{port}/depot/"])
        run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD})
        lines = deliver_run(
            run_dir,
            [request],
            _ftp_environment(tmp_path, port),
            project_root=_project(tmp_path),
            delays=(0, 0),
        )

        assert lines[0].state == state
        assert lines[0].attempts == attempts
        if state == "delivered":
            assert (server_root / "depot" / "head_last.tif").read_bytes() == HEAD
        else:
            assert lines[0].error is not None and "451" in lines[0].error
            assert not (server_root / "depot" / "head_last.tif").exists()
        assert _no_parts(server_root)


def test_ftp_overwrites_existing_file(
    tmp_path: Path,
) -> None:
    server_root = tmp_path / "srv"
    depot = server_root / "depot"
    depot.mkdir(parents=True)
    (depot / "head_last.tif").write_bytes(b"the bytes of yesterday")
    with ftp_server(server_root, refuse_overwrite=True) as port:
        request = _request(deliver_to=[f"ftp://127.0.0.1:{port}/depot/"])
        run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD})
        lines = deliver_run(
            run_dir,
            [request],
            _ftp_environment(tmp_path, port),
            project_root=_project(tmp_path),
            delays=(0, 0),
        )

        assert lines[0].state == "delivered"
        assert lines[0].attempts == 1
        assert (depot / "head_last.tif").read_bytes() == HEAD


def test_ftp_single_file_name(tmp_path: Path) -> None:
    server_root = tmp_path / "srv"
    (server_root / "depot").mkdir(parents=True)
    with ftp_server(server_root) as port:
        request = _request(file="one.tif", deliver_to=[f"ftp://127.0.0.1:{port}/depot/one.tif"])
        run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD})
        deliver_run(
            run_dir,
            [request],
            _ftp_environment(tmp_path, port),
            project_root=_project(tmp_path),
            delays=(0, 0),
        )

        assert (server_root / "depot" / "one.tif").read_bytes() == HEAD
        assert not (server_root / "depot" / "head_last.tif").exists()


@pytest.mark.allow_subprocess
def test_ftps_push_under_tls(tmp_path: Path) -> None:
    server_context = server_tls(*self_signed(tmp_path))
    client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_context.check_hostname = False
    client_context.verify_mode = ssl.CERT_NONE
    server_root = tmp_path / "srv"
    (server_root / "depot").mkdir(parents=True)
    source = tmp_path / "head_last.tif"
    source.write_bytes(HEAD)

    with ftp_server(server_root, tls=server_context) as port:
        destination = parse_destination(f"ftps://127.0.0.1:{port}/depot/")
        credential = HostCredential(
            prefix=f"ftps://127.0.0.1:{port}/", user="user", password="secret"
        )
        bounds = Bounds(allowed_hosts=frozenset({"127.0.0.1"}), timeout_s=10.0)

        PROBES["ftps"](destination, credential, bounds, context=client_context)
        PUSHERS["ftps"](
            source, destination, "head_last.tif", credential, bounds, context=client_context
        )

        assert (server_root / "depot" / "head_last.tif").read_bytes() == HEAD
        assert _no_parts(server_root)


def _ftps_attempt(
    tmp_path: Path, tls: ssl.SSLContext | None
) -> tuple[BaseException, BaseException, list[str], Path]:
    """Probe then push with the default client context; return both errors and the commands."""
    server_root = tmp_path / "srv"
    (server_root / "depot").mkdir(parents=True)
    source = tmp_path / "head_last.tif"
    source.write_bytes(HEAD)
    commands: list[str] = []
    with ftp_server(server_root, tls=tls, commands=commands) as port:
        destination = parse_destination(f"ftps://127.0.0.1:{port}/depot/")
        credential = HostCredential(
            prefix=f"ftps://127.0.0.1:{port}/", user="user", password="secret"
        )
        bounds = Bounds(allowed_hosts=frozenset({"127.0.0.1"}), timeout_s=5.0)
        with pytest.raises(NetworkError) as probed:
            PROBES["ftps"](destination, credential, bounds)
        with pytest.raises(ftplib.all_errors) as pushed:
            PUSHERS["ftps"](source, destination, "head_last.tif", credential, bounds)
    return probed.value, pushed.value, commands, server_root


@pytest.mark.allow_subprocess
def test_ftps_refuses_self_signed(tmp_path: Path) -> None:
    tls = server_tls(*self_signed(tmp_path))

    probed, pushed, commands, server_root = _ftps_attempt(tmp_path, tls)

    assert isinstance(probed.__cause__, ssl.SSLCertVerificationError)
    assert isinstance(pushed, ssl.SSLCertVerificationError)
    assert "PASS" not in commands and "STOR" not in commands
    assert list((server_root / "depot").iterdir()) == []


def test_ftps_never_falls_back(tmp_path: Path) -> None:
    probed, pushed, commands, server_root = _ftps_attempt(tmp_path, None)

    assert "does not answer" in str(probed)
    assert isinstance(pushed, ftplib.error_perm)
    assert commands.count("AUTH") == 2
    assert "PASS" not in commands and "STOR" not in commands
    assert list((server_root / "depot").iterdir()) == []


class _FakeSFTP:
    """The SFTP client of the stand-in: one folder, the commands a push sends."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.cwd = "/"

    def _local(self, name: str) -> Path:
        target = name if name.startswith("/") else posixpath.join(self.cwd, name)
        return self.root / posixpath.normpath(target).lstrip("/")

    def chdir(self, name: str) -> None:
        target = self._local(name)
        if not target.is_dir():
            raise OSError(f"no folder {name}")
        self.cwd = posixpath.normpath(
            name if name.startswith("/") else posixpath.join(self.cwd, name)
        )

    def mkdir(self, name: str) -> None:
        self._local(name).mkdir()

    def putfo(self, handle: Any, name: str, file_size: int | None = None) -> None:
        del file_size
        self._local(name).write_bytes(handle.read())

    def posix_rename(self, old: str, new: str) -> None:
        target = self._local(new)
        if target.exists():
            raise OSError(f"{new} exists")
        os.replace(self._local(old), target)

    def remove(self, name: str) -> None:
        self._local(name).unlink()

    def stat(self, name: str) -> Any:
        return types.SimpleNamespace(st_size=self._local(name).stat().st_size)

    def close(self) -> None:
        pass


class _FakeTransport:
    """The transport of the stand-in: a fixed server key and one authentication."""

    def __init__(self, address: tuple[str, int], root: Path, refusal: str | None) -> None:
        self.address = address
        self.sftp = _FakeSFTP(root)
        self.refusal = refusal
        self.closed = False

    def start_client(self, timeout: float | None = None) -> None:
        del timeout

    def get_remote_server_key(self) -> Any:
        return types.SimpleNamespace(asbytes=lambda: FINGERPRINT_KEY)

    def auth_password(self, user: str, secret: str) -> None:
        del user, secret
        if self.refusal is not None:
            raise OSError(self.refusal)

    def auth_publickey(self, user: str, key: Any) -> None:
        del user
        if key.kind != "ssh-ed25519":
            raise OSError("the stand-in takes the ed25519 key of the test")

    def open_sftp(self) -> _FakeSFTP:
        return self.sftp

    def close(self) -> None:
        self.closed = True


def _sftp_environment(credentials: Path) -> Environment:
    """Return the environment of a delivery to the sftp stand-in on 127.0.0.1."""
    return Environment(
        credentials=credentials, bounds=Bounds(allowed_hosts=frozenset({"127.0.0.1"}))
    )


def _fake_paramiko(root: Path, *, refusal: str | None = None) -> types.ModuleType:
    """Return a module that stands where paramiko would."""
    module = types.ModuleType("paramiko")

    def transport(address: tuple[str, int]) -> _FakeTransport:
        return _FakeTransport(address, root, refusal)

    def from_path(path: str) -> Any:
        text = Path(path).read_text(encoding="utf-8")
        return types.SimpleNamespace(kind=text.split()[0])

    module.Transport = transport
    module.PKey = types.SimpleNamespace(from_path=from_path)
    return module


def test_sftp_push(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server_root = _sftp_root(tmp_path)
    monkeypatch.setitem(sys.modules, "paramiko", _fake_paramiko(server_root))
    credentials = _sftp_credentials(tmp_path, _fingerprint_of(FINGERPRINT_KEY))
    request = _request(deliver_to=["sftp://127.0.0.1/depot/"])
    run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD})

    lines = deliver_run(
        run_dir,
        [request],
        _sftp_environment(credentials),
        project_root=_project(tmp_path),
        delays=(0, 0),
    )

    assert lines[0].state == "delivered" and lines[0].attempts == 1
    assert (server_root / "depot" / "head_last.tif").read_bytes() == HEAD
    assert _no_parts(server_root)


def test_sftp_wrong_fingerprint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server_root = _sftp_root(tmp_path)
    monkeypatch.setitem(sys.modules, "paramiko", _fake_paramiko(server_root))
    credentials = _sftp_credentials(tmp_path, "not-the-key-the-server-shows")
    request = _request(deliver_to=["sftp://127.0.0.1/depot/"])
    run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD})

    lines = deliver_run(
        run_dir,
        [request],
        _sftp_environment(credentials),
        project_root=_project(tmp_path),
        delays=(0, 0),
    )

    assert lines[0].state == "failed" and lines[0].attempts == DELIVERY_ATTEMPTS
    assert lines[0].error is not None and "shows the fingerprint" in lines[0].error
    assert not (server_root / "depot" / "head_last.tif").exists()


def test_sftp_ed25519_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server_root = _sftp_root(tmp_path)
    monkeypatch.setitem(sys.modules, "paramiko", _fake_paramiko(server_root))
    key_file = tmp_path / "home" / "id_ed25519"
    key_file.parent.mkdir(parents=True)
    key_file.write_text("ssh-ed25519 the private key of the test\n", encoding="utf-8")
    credentials = _credentials(
        tmp_path,
        '[[host]]\nprefix = "sftp://127.0.0.1/"\nuser = "user"\n'
        f'key_file = "{key_file}"\n'
        f'host_fingerprint = "SHA256:{_fingerprint_of(FINGERPRINT_KEY)}"\n',
    )
    request = _request(deliver_to=["sftp://127.0.0.1/depot/"])
    run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD})

    lines = deliver_run(
        run_dir,
        [request],
        _sftp_environment(credentials),
        project_root=_project(tmp_path),
        delays=(0, 0),
    )

    assert lines[0].state == "delivered", lines[0].error
    assert (server_root / "depot" / "head_last.tif").read_bytes() == HEAD


def _pending_run(tmp_path: Path, address: str) -> Path:
    """Write a sealed run whose one file has a pending line to *address*."""
    request = _request(deliver_to=[address])
    run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD}, config=_config_of(address))
    target = address + "head_last.tif"
    append_published(
        run_dir,
        _delivery_line("exports/head_last.tif", target, HEAD, "pending", attempts=0),
    )
    return run_dir


def test_pending_refuses_host(tmp_path: Path, ftp_depot: tuple[int, Path]) -> None:
    port, server_root = ftp_depot
    address = f"ftp://127.0.0.1:{port}/depot/"
    run_dir = _pending_run(tmp_path, address)
    environment = Environment(
        credentials=_ftp_credentials(tmp_path, f"ftp://127.0.0.1:{port}/"),
        bounds=Bounds(allowed_hosts=frozenset({"other.example.org"}), timeout_s=5.0),
    )

    lines = deliver_pending(run_dir, environment, project_root=_project(tmp_path), delays=(0, 0))

    assert [line.state for line in lines] == ["failed"]
    assert "not among the hosts this call allows" in (lines[0].error or "")
    assert list((server_root / "depot").iterdir()) == []


def test_pending_refuses_private_address(tmp_path: Path, ftp_depot: tuple[int, Path]) -> None:
    port, server_root = ftp_depot
    address = f"ftp://127.0.0.1:{port}/depot/"
    run_dir = _pending_run(tmp_path, address)
    environment = Environment(credentials=_ftp_credentials(tmp_path, f"ftp://127.0.0.1:{port}/"))

    lines = deliver_pending(run_dir, environment, project_root=_project(tmp_path), delays=(0, 0))

    assert [line.state for line in lines] == ["failed"]
    assert "non-public IP address" in (lines[0].error or "")
    assert list((server_root / "depot").iterdir()) == []


def test_pending_refuses_folder(tmp_path: Path) -> None:
    depot = tmp_path / "depot"
    depot.mkdir()
    run_dir = _pending_run(tmp_path, str(depot) + "/")
    project = _project(tmp_path)
    environment = Environment(bounds=Bounds(allowed_roots=(project,)))

    lines = deliver_pending(run_dir, environment, project_root=project, delays=(0, 0))

    assert [line.state for line in lines] == ["failed"]
    assert "outside the roots this call allows" in (lines[0].error or "")
    assert list(depot.iterdir()) == []


def test_pending_warns_clear_ftp(
    tmp_path: Path, ftp_depot: tuple[int, Path], caplog: pytest.LogCaptureFixture
) -> None:
    port, server_root = ftp_depot
    run_dir = _pending_run(tmp_path, f"ftp://127.0.0.1:{port}/depot/")

    with caplog.at_level(logging.WARNING, logger="hydromodpy.project.deliver"):
        lines = deliver_pending(
            run_dir,
            _ftp_environment(tmp_path, port),
            project_root=_project(tmp_path),
            delays=(0, 0),
        )

    assert [line.state for line in lines] == ["delivered"]
    told = [record for record in caplog.records if "sends its password in clear" in record.message]
    assert len(told) == 1
    assert (server_root / "depot" / "head_last.tif").read_bytes() == HEAD


def test_pending_pushes_listed_pair(tmp_path: Path) -> None:
    depot = tmp_path / "depot"
    depot.mkdir()
    target = str(depot) + "/head_last.tif"
    request = _request(deliver_to=[str(depot) + "/"])
    run_dir = _make_run(
        tmp_path, request, {"head_last.tif": HEAD}, config=_config_of(str(depot) + "/")
    )
    append_published(
        run_dir,
        _delivery_line("exports/head_last.tif", target, HEAD, "pending", attempts=0),
    )

    lines = deliver_pending(run_dir, Environment(), project_root=_project(tmp_path), delays=(0, 0))

    assert [line.state for line in lines] == ["delivered"]
    assert (depot / "head_last.tif").read_bytes() == HEAD
    assert _states(run_dir) == ["pending", "pending", "delivered"]


def test_pending_skips_delivered_pair(tmp_path: Path) -> None:
    depot = tmp_path / "depot"
    depot.mkdir()
    target = str(depot) + "/head_last.tif"
    request = _request(deliver_to=[str(depot) + "/"])
    run_dir = _make_run(
        tmp_path, request, {"head_last.tif": HEAD}, config=_config_of(str(depot) + "/")
    )
    (depot / "head_last.tif").write_bytes(HEAD)
    append_published(
        run_dir,
        _delivery_line("exports/head_last.tif", target, HEAD, "delivered", attempts=1),
    )

    lines = deliver_pending(run_dir, Environment(), project_root=_project(tmp_path), delays=(0, 0))

    assert lines == ()
    assert _states(run_dir) == ["delivered"]


def test_pending_repushes_changed_bytes(tmp_path: Path) -> None:
    depot = tmp_path / "depot"
    depot.mkdir()
    target = str(depot) + "/head_last.tif"
    request = _request(deliver_to=[str(depot) + "/"])
    run_dir = _make_run(
        tmp_path, request, {"head_last.tif": HEAD}, config=_config_of(str(depot) + "/")
    )
    append_published(
        run_dir,
        _delivery_line("exports/head_last.tif", target, OTHER, "delivered", attempts=1),
    )

    deliver_pending(run_dir, Environment(), project_root=_project(tmp_path), delays=(0, 0))

    assert (depot / "head_last.tif").read_bytes() == HEAD
    last = read_published(run_dir)[-1]
    assert last.state == "delivered"
    assert last.sha256 == hashlib.sha256(HEAD).hexdigest()


def test_pending_pushes_pair_from_lines(tmp_path: Path) -> None:
    depot = tmp_path / "depot"
    depot.mkdir()
    target = str(depot) + "/head_last.tif"
    run_dir = _make_run(tmp_path, None, {"head_last.tif": HEAD})
    append_published(
        run_dir,
        _delivery_line(
            "exports/head_last.tif", target, HEAD, "failed", attempts=3, error="the server was down"
        ),
    )

    lines = deliver_pending(run_dir, Environment(), project_root=_project(tmp_path), delays=(0, 0))

    assert [line.state for line in lines] == ["delivered"]
    assert (depot / "head_last.tif").read_bytes() == HEAD


def test_pending_needs_a_seal(tmp_path: Path) -> None:
    run_dir = _make_run(tmp_path, None, {"head_last.tif": HEAD}, sealed=False)

    with pytest.raises(ExportError, match="only a sealed run is delivered"):
        deliver_pending(run_dir, Environment(), project_root=_project(tmp_path), delays=(0, 0))


def test_password_never_reaches_a_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    server_root = _sftp_root(tmp_path)
    refusal = f"authentication refused the password {SECRET}"
    monkeypatch.setitem(sys.modules, "paramiko", _fake_paramiko(server_root, refusal=refusal))
    credentials = _sftp_credentials(tmp_path, _fingerprint_of(FINGERPRINT_KEY))
    request = _request(deliver_to=["sftp://127.0.0.1/depot/"])
    run_dir = _make_run(tmp_path, request, {"head_last.tif": HEAD})

    lines = deliver_run(
        run_dir,
        [request],
        _sftp_environment(credentials),
        project_root=_project(tmp_path),
        delays=(0, 0),
    )

    assert lines[0].state == "failed"
    assert lines[0].error is not None and "<secret>" in lines[0].error
    written = (run_dir / "published.jsonl").read_text(encoding="utf-8")
    assert SECRET not in written
    assert "<secret>" in written


@pytest.mark.parametrize("windows", [True, False])
def test_path_pusher_native_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    """On Windows the ``.part`` copy, its rename and the size check use the long form; elsewhere
    the paths stay as given."""
    from hydromodpy.project import deliver as deliver_module
    from hydromodpy.results.exporters.destination import Destination
    from tests._helpers.windows_os import WindowsOs

    if windows:
        monkeypatch.setattr(deliver_module, "os", WindowsOs())
    seen: list[str] = []
    real = deliver_module.native_io_path

    def record(path: Path | str) -> str:
        seen.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(deliver_module, "native_io_path", record)
    source = tmp_path / "report.html"
    source.write_text("body", encoding="utf-8")
    folder = tmp_path / "out"
    folder.mkdir()
    destination = Destination(
        text=str(folder) + "/", scheme="path", host=None, port=None, path=str(folder), folder=True
    )
    bounds = Bounds.__new__(Bounds)

    PUSHERS["path"](source, destination, "sub/report.html", None, bounds)

    assert (folder / "sub" / "report.html").read_text(encoding="utf-8") == "body"
    if windows:
        assert "report.html" + PART_SUFFIX in seen
        assert "report.html" in seen
    else:
        assert seen == []
    assert not list(folder.rglob("*" + PART_SUFFIX))
