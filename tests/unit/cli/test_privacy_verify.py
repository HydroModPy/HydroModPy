"""``hmp privacy verify`` checks a purge certificate: valid JSON with the five fields, mode 600 if strict."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ._hmp import run_main as _run

CERTIFICATE = {
    "sim_id": "abc",
    "timestamp_utc": "2026-01-01T00:00:00+00:00",
    "operator": "tester",
    "reason": "test",
    "sha256_snapshot": "a" * 64,
}

# (certificate text, file mode, flags, exit code)
REFUSED = [
    pytest.param("{not valid", 0o600, [], 14, id="invalid json"),
    pytest.param(json.dumps(CERTIFICATE), 0o644, ["--strict"], 14, id="strict with mode 644"),
]


def write_certificate(tmp_path: Path, text: str, mode: int) -> Path:
    path = tmp_path / "cert.json"
    path.write_text(text)
    os.chmod(path, mode)
    return path


def test_a_missing_certificate_is_not_found(monkeypatch, tmp_path) -> None:
    assert _run(monkeypatch, ["hmp", "privacy", "verify", str(tmp_path / "nope.json")]) == 10


@pytest.mark.parametrize(("text", "mode", "flags", "code"), REFUSED)
def test_refusals(monkeypatch, tmp_path, text, mode, flags, code) -> None:
    cert = write_certificate(tmp_path, text, mode)

    assert _run(monkeypatch, ["hmp", "privacy", "verify", *flags, str(cert)]) == code


def test_a_good_certificate_verifies(monkeypatch, tmp_path, capsys) -> None:
    cert = write_certificate(tmp_path, json.dumps(CERTIFICATE), 0o600)

    assert _run(monkeypatch, ["hmp", "privacy", "verify", str(cert)]) == 0
    assert "verifies" in capsys.readouterr().out.lower()
