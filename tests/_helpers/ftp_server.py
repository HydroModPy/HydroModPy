"""A small FTP and FTPS server for tests, on socketserver, no dependency.

One user, one root folder, passive mode, and optionally explicit TLS. Two
switches make the failures a delivery retries play the same way: ``fail_stor``
refuses that many ``STOR`` commands with ``451``, and ``refuse_overwrite``
refuses a ``RNTO`` onto a file that exists, so the caller has to delete it
first. The server runs in a thread of the test process and binds a free port.
"""

from __future__ import annotations

import os
import shutil
import socket
import socketserver
import ssl
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest


class _Handler(socketserver.StreamRequestHandler):
    """One control connection of the test server."""

    def setup(self) -> None:
        super().setup()
        self.cwd = Path("/")
        self.user = ""
        self.authenticated = False
        self.data_socket: socket.socket | None = None
        self.rename_from: Path | None = None
        self.protected = False

    def reply(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())
        self.wfile.flush()

    def local(self, name: str) -> Path:
        """Return where *name* lives under the root of the server."""
        target = Path(name) if name.startswith("/") else self.cwd / name
        return self.server.root / os.path.normpath(str(target)).lstrip("/")

    def data_connection(self) -> socket.socket:
        connection, _ = self.data_socket.accept()
        self.data_socket.close()
        self.data_socket = None
        if self.protected:
            connection = self.server.tls.wrap_socket(connection, server_side=True)
        return connection

    def handle(self) -> None:
        self.reply("220 hydromodpy test ftp")
        while True:
            try:
                raw = self.rfile.readline()
            except OSError:
                return
            if not raw:
                return
            line = raw.decode().rstrip("\r\n")
            command, _, argument = line.partition(" ")
            command = command.upper()
            self.server.commands.append(command)
            if command == "AUTH" and self.server.tls:
                self.reply("234 TLS")
                self.connection = self.server.tls.wrap_socket(self.connection, server_side=True)
                self.rfile = self.connection.makefile("rb")
                self.wfile = self.connection.makefile("wb")
            elif command == "PBSZ":
                self.reply("200 ok")
            elif command == "PROT":
                self.protected = argument.upper() == "P"
                self.reply("200 ok")
            elif command == "USER":
                self.user = argument
                self.reply("331 password")
            elif command == "PASS":
                self.authenticated = (self.user, argument) == self.server.login
                self.reply("230 logged in" if self.authenticated else "530 refused")
            elif not self.authenticated and command != "QUIT":
                self.reply("530 log in first")
            elif command == "TYPE":
                self.reply("200 type set")
            elif command == "PWD":
                self.reply(f'257 "{self.cwd}"')
            elif command == "CWD":
                target = self.local(argument)
                if target.is_dir():
                    self.cwd = Path(os.path.normpath(str(self.cwd / argument)))
                    self.reply("250 folder")
                else:
                    self.reply("550 no such folder")
            elif command == "MKD":
                try:
                    self.local(argument).mkdir()
                except OSError:
                    self.reply("550 cannot create")
                else:
                    self.reply("257 made")
            elif command == "PASV":
                listener = socket.socket()
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                self.data_socket = listener
                port = listener.getsockname()[1]
                self.reply(f"227 Entering Passive Mode (127,0,0,1,{port // 256},{port % 256})")
            elif command == "STOR":
                self._store(argument)
            elif command == "SIZE":
                target = self.local(argument)
                self.reply(f"213 {target.stat().st_size}" if target.is_file() else "550 no file")
            elif command == "RNFR":
                self.rename_from = self.local(argument)
                self.reply("350 ready")
            elif command == "RNTO":
                self._rename(argument)
            elif command == "DELE":
                try:
                    self.local(argument).unlink()
                except OSError:
                    self.reply("550 cannot remove")
                else:
                    self.reply("250 gone")
            elif command == "NOOP":
                self.reply("200 ok")
            elif command == "QUIT":
                self.reply("221 bye")
                return
            else:
                self.reply("502 not implemented")

    def _store(self, argument: str) -> None:
        if self.server.fail_stor > 0:
            self.server.fail_stor -= 1
            self.data_connection().close()
            self.reply("451 not now")
            return
        self.reply("150 sending")
        connection = self.data_connection()
        with self.local(argument).open("wb") as handle:
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                handle.write(chunk)
        if isinstance(connection, ssl.SSLSocket):
            try:
                connection = connection.unwrap()
            except (OSError, ValueError):
                pass
        connection.close()
        self.reply("226 written")

    def _rename(self, argument: str) -> None:
        target = self.local(argument)
        if self.rename_from is None:
            self.reply("503 no source")
        elif self.server.refuse_overwrite and target.exists():
            self.reply("550 target exists")
        else:
            os.replace(self.rename_from, target)
            self.reply("250 renamed")


class _Server(socketserver.ThreadingTCPServer):
    """A threaded server that remembers the root, the login and the switches."""

    daemon_threads = True
    allow_reuse_address = True
    root: Path
    login: tuple[str, str]
    tls: ssl.SSLContext | None
    fail_stor: int
    refuse_overwrite: bool
    commands: list[str]
    """Every command name the server read, in order, for a test to look at."""


@contextmanager
def ftp_server(
    root: Path,
    *,
    login: tuple[str, str] = ("user", "secret"),
    tls: ssl.SSLContext | None = None,
    fail_stor: int = 0,
    refuse_overwrite: bool = False,
    commands: list[str] | None = None,
) -> Iterator[int]:
    """Run a server on 127.0.0.1 and yield its port; stop it on exit.

    *commands*, when given, receives the name of every command the server reads.
    """
    server = _Server(("127.0.0.1", 0), _Handler)
    server.root = Path(root)
    server.login = login
    server.tls = tls
    server.fail_stor = fail_stor
    server.refuse_overwrite = refuse_overwrite
    server.commands = [] if commands is None else commands
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def self_signed(folder: Path) -> tuple[Path, Path]:
    """Make a self-signed certificate for 127.0.0.1 with openssl; skip when it is absent."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is not installed")
    certificate = folder / "cert.pem"
    key = folder / "key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ],
        check=True,
        capture_output=True,
    )
    return certificate, key


def server_tls(certificate: Path, key: Path) -> ssl.SSLContext:
    """Return the server context of a self-signed certificate made by the test."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    return context


__all__ = ["ftp_server", "self_signed", "server_tls"]
