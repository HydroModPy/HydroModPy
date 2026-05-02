from __future__ import annotations

import importlib.util
import json
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "install" / "verify_dev_env.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_dev_env", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_file_url_to_path_round_trips_local_uri(tmp_path: Path) -> None:
    module = _load_module()

    expected = tmp_path.resolve()
    actual = module._file_url_to_path(expected.as_uri())

    assert actual is not None
    assert actual.resolve() == expected


def test_collect_issues_reports_missing_distribution(monkeypatch) -> None:
    module = _load_module()

    def _raise(_name: str):
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(module.metadata, "distribution", _raise)
    monkeypatch.setattr(module, "find_spec", lambda _name: object())

    version, editable_root, issues = module.collect_issues(
        dist_name="hydromodpy",
        expected_editable_root=None,
        require_docs=False,
    )

    assert version is None
    assert editable_root is None
    assert any("not installed as a distribution" in issue for issue in issues)


def test_collect_issues_accepts_matching_editable_distribution(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path.resolve()
    direct_url = json.dumps(
        {
            "url": repo_root.as_uri(),
            "dir_info": {"editable": True},
        }
    )
    fake_dist = SimpleNamespace(
        version="0.5.0",
        read_text=lambda name: direct_url if name == "direct_url.json" else None,
    )

    monkeypatch.setattr(module.metadata, "distribution", lambda _name: fake_dist)
    monkeypatch.setattr(module, "find_spec", lambda _name: object())

    version, editable_root, issues = module.collect_issues(
        dist_name="hydromodpy",
        expected_editable_root=repo_root,
        require_docs=True,
    )

    assert version == "0.5.0"
    assert editable_root == repo_root
    assert issues == []


def test_collect_issues_reports_missing_core_and_docs_modules(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path.resolve()
    direct_url = json.dumps(
        {
            "url": repo_root.as_uri(),
            "dir_info": {"editable": True},
        }
    )
    fake_dist = SimpleNamespace(
        version="0.5.0",
        read_text=lambda name: direct_url if name == "direct_url.json" else None,
    )

    def _fake_find_spec(name: str):
        if name in {"zarr", "nbsphinx"}:
            return None
        return object()

    monkeypatch.setattr(module.metadata, "distribution", lambda _name: fake_dist)
    monkeypatch.setattr(module, "find_spec", _fake_find_spec)

    _version, _editable_root, issues = module.collect_issues(
        dist_name="hydromodpy",
        expected_editable_root=repo_root,
        require_docs=True,
    )

    assert any("Missing core runtime modules: zarr." == issue for issue in issues)
    assert any("Missing docs modules: nbsphinx." == issue for issue in issues)
