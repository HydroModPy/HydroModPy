from __future__ import annotations

from pathlib import Path

from hydromodpy.analysis.comparison import run_backend


def test_run_child_with_hmp_uses_stable_utf8_decoding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "child.toml"
    config_path.write_text("", encoding="utf-8")
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = "sim_id: 12345678-1234-1234-1234-123456789abc\n"
        stderr = "warning: replacement char is allowed \ufffd\n"

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr(run_backend.subprocess, "run", fake_run)

    result = run_backend.run_child_with_hmp(config_path, timeout_seconds=5.0)

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert result.succeeded
    assert result.sim_id == "12345678-1234-1234-1234-123456789abc"
