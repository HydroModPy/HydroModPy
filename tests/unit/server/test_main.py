"""The start of the server: what it refuses, what it cleans, the line it prints."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import hydromodpy as hmp
from hydromodpy_server.__main__ import WARM, clean_inbox, prepare
from tests.scenarios.launcher import isolated_env, tree_root

DIGEST = "sha256:" + "b" * 64


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("HMP_IMAGE_TAG", raising=False)
    monkeypatch.delenv("HMP_IMAGE_DIGEST", raising=False)
    (tmp_path / "root").mkdir()
    (tmp_path / "creds").mkdir()
    return tmp_path / "root"


REFUSED = {
    "a root that does not exist": (["--root", "{tmp}/nowhere"], {}, "does not exist"),
    "credentials under the root": (
        ["--root", "{tmp}/root", "--credentials-dir", "{tmp}/root/creds"],
        {},
        "is under the root",
    ),
    "credentials that are the root": (
        ["--root", "{tmp}/root", "--credentials-dir", "{tmp}/root"],
        {},
        "is under the root",
    ),
    "credentials that do not exist": (
        ["--root", "{tmp}/root", "--credentials-dir", "{tmp}/absent"],
        {},
        "does not exist",
    ),
    "an image without its digest": (
        ["--root", "{tmp}/root"],
        {"HMP_IMAGE_TAG": "t1"},
        "runs in the image t1 without HMP_IMAGE_DIGEST: start the container with -e",
    ),
    "a digest that is not one": (
        ["--root", "{tmp}/root"],
        {"HMP_IMAGE_TAG": "t1", "HMP_IMAGE_DIGEST": "abc"},
        "expected sha256:",
    ),
    "a warm-up file that is absent": (
        ["--root", "{tmp}/root", "--warm", "{tmp}/none.toml"],
        {},
        "warm-up file",
    ),
    "a ceiling that is not positive": (
        ["--root", "{tmp}/root", "--max-download-bytes", "0"],
        {},
        "max_download_bytes",
    ),
    "a host with a scheme": (
        ["--root", "{tmp}/root", "--allow-host", "https://example.org"],
        {},
        "scheme",
    ),
}


@pytest.mark.parametrize(("argv", "env", "phrase"), REFUSED.values(), ids=list(REFUSED))
def test_a_start_that_would_be_wrong_stops_with_code_2(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    env: dict[str, str],
    phrase: str,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit) as stopped:
        prepare([item.replace("{tmp}", str(root.parent)) for item in argv])
    assert stopped.value.code == 2
    assert phrase in capsys.readouterr().err


def test_no_root_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        prepare([])
    assert stopped.value.code == 2
    assert "--root" in capsys.readouterr().err


def test_a_good_start_reads_every_option(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMP_IMAGE_TAG", "t1")
    monkeypatch.setenv("HMP_IMAGE_DIGEST", DIGEST)
    settings, host, port, warm = prepare(
        [
            *("--root", str(root), "--credentials-dir", str(root.parent / "creds")),
            *("--allow-host", "Example.org", "--max-download-bytes", "5", "--port", "0"),
            *("--host", "0.0.0.0"),
        ]
    )
    assert (settings.root, settings.credentials_dir) == (root, root.parent / "creds")
    assert settings.bounds.allowed_hosts == frozenset({"example.org"})
    assert settings.bounds.max_download_bytes == 5
    assert (host, port, warm) == ("0.0.0.0", 0, [WARM])


def test_without_options_any_public_host_is_allowed_and_the_default_port_is_8765(
    root: Path,
) -> None:
    settings, host, port, _ = prepare(["--root", str(root)])
    assert settings.bounds.allowed_hosts is None
    assert (host, port, settings.credentials_dir) == ("127.0.0.1", 8765, None)


def test_a_start_removes_the_half_written_uploads_and_only_them(root: Path) -> None:
    inbox = root / ".inbox"
    inbox.mkdir()
    for name in ("a.part", "b.part", "keep.txt"):
        (inbox / name).write_bytes(b"x")
    clean_inbox(root)
    assert [path.name for path in inbox.iterdir()] == ["keep.txt"]
    clean_inbox(root.parent / "creds")


def test_the_warm_up_document_reads_without_an_error(tmp_path: Path) -> None:
    document: dict[str, Any] = json.loads(WARM.read_text(encoding="utf-8"))
    errors = [d for d in hmp.check(document, base=tmp_path) if d.severity == "error"]
    assert errors == []


@pytest.mark.allow_subprocess
def test_the_server_prints_its_address_serves_and_stops_on_a_signal(tmp_path: Path) -> None:
    (tmp_path / "root").mkdir()
    small = tmp_path / "small.json"
    small.write_text(json.dumps({"geographic": {"source_mode": "synthetic"}}), encoding="utf-8")
    env = isolated_env(tmp_path / "home", tmp_path / "cache", tmp_path / "state", tmp_path / "tmp")
    env["PYTHONPATH"] = str(tree_root())
    env.pop("HMP_IMAGE_TAG", None)
    argv = [sys.executable, "-m", "hydromodpy_server", "--root", str(tmp_path / "root")]
    argv += ["--port", "0", "--warm", str(small)]
    process = subprocess.Popen(
        argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    watchdog = threading.Timer(120, process.kill)
    watchdog.start()
    try:
        assert process.stdout is not None
        line = process.stdout.readline()
        assert line.startswith("serving on http://127.0.0.1:")
        with urllib.request.urlopen(line.split()[-1] + "/v1/health", timeout=30) as answer:
            assert json.loads(answer.read())["version"] == hmp.__version__
        process.terminate()
        code = process.wait(timeout=60)
        if os.name == "posix":
            assert code == 0
    finally:
        watchdog.cancel()
        process.kill()
        process.wait()
