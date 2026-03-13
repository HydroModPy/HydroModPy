from __future__ import annotations

from pathlib import Path

from launchers.output_paths import resolve_launcher_output_root


def _paths_root(tmp_path: Path) -> Path:
    root = (tmp_path / "launcher_output_paths").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_resolve_launcher_output_root_prefers_env_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = _paths_root(tmp_path)
    monkeypatch.setenv("HYDROMODPY_OUT_PATH", str(root / "env-override"))

    resolved, resolution = resolve_launcher_output_root(
        configured_out_dir=root / "repo" / "results",
        repo_root=root / "repo",
        fallback_root=root / "fallback",
    )

    assert resolved == (root / "env-override").resolve()
    assert resolution == "env_override"


def test_resolve_launcher_output_root_redirects_repo_local_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = _paths_root(tmp_path)
    monkeypatch.delenv("HYDROMODPY_OUT_PATH", raising=False)
    resolved, resolution = resolve_launcher_output_root(
        configured_out_dir=root / "repo" / "examples" / "results",
        repo_root=root / "repo",
        fallback_root=root / "fallback",
    )

    assert resolved == (root / "fallback").resolve()
    assert resolution == "repo_redirect"


def test_resolve_launcher_output_root_keeps_external_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = _paths_root(tmp_path)
    monkeypatch.delenv("HYDROMODPY_OUT_PATH", raising=False)
    configured = root / "external" / "results"

    resolved, resolution = resolve_launcher_output_root(
        configured_out_dir=configured,
        repo_root=root / "repo",
        fallback_root=root / "fallback",
    )

    assert resolved == configured.resolve()
    assert resolution == "configured"
