"""The ``whitebox`` and ``windows`` markers of ``tests/conftest.py``, played in a nested session."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

SKIPPED = "a Windows behaviour, proved by the weekly Windows job"

# One row per refusal sentence, compared word for word. The last column says whether
# the nested session plays the test as on Windows, so that the body and its own skip run.
REFUSALS = [
    (
        "windows test skipped by its own reason",
        "import pytest\n\n@pytest.mark.windows\ndef test_x():\n    pytest.skip('no admin rights')\n",
        "HMP_REQUIRE_WINDOWS is set and no admin rights",
        True,
    ),
    (
        "windows test skipped by the system",
        "import pytest\n\n@pytest.mark.windows\ndef test_x():\n    pass\n",
        f"HMP_REQUIRE_WINDOWS is set and {SKIPPED}",
        False,
    ),
]


@pytest.fixture
def plugin(request):
    """The module of ``tests/conftest.py`` that the outer session loaded."""
    return next(
        p
        for p in request.config.pluginmanager.get_plugins()
        if str(getattr(p, "__file__", "")).endswith(str(Path("tests") / "conftest.py"))
    )


@pytest.fixture
def suite(pytester, request, monkeypatch, plugin):
    """Run a nested session that uses the conftest already loaded by the outer one."""
    # The nested session must not delete the scratch root of the outer one.
    monkeypatch.setattr(plugin, "_OWNS_TEST_SCRATCH", False)
    monkeypatch.delenv("HMP_REQUIRE_WINDOWS", raising=False)
    pytester.makeini((Path(request.config.rootpath) / "pytest.ini").read_text())

    def run(files: dict[str, str]):
        for name, source in files.items():
            pytester.makepyfile(**{name: source})
        return pytester.inline_run("-p", "no:cacheprovider", plugins=[plugin])

    return run


@pytest.mark.skipif(os.name == "nt", reason="the proof is the skip on a system other than Windows")
def test_a_windows_test_is_skipped_elsewhere_with_one_reason(suite):
    run = suite({"test_a": "import pytest\n\n@pytest.mark.windows\ndef test_x():\n    pass\n"})
    passed, skipped, failed = run.listoutcomes()
    assert (len(passed), len(skipped), len(failed)) == (0, 1, 0)
    assert SKIPPED in str(skipped[0].longrepr)


@pytest.mark.skipif(os.name == "nt", reason="the proof is the skip on a system other than Windows")
@pytest.mark.parametrize(
    ("case", "source", "sentence", "on_windows"), REFUSALS, ids=[r[0] for r in REFUSALS]
)
def test_a_skipped_windows_test_fails_under_the_variable(
    suite, plugin, monkeypatch, case, source, sentence, on_windows
):
    monkeypatch.setenv("HMP_REQUIRE_WINDOWS", "1")
    monkeypatch.setattr(plugin, "_ON_WINDOWS", on_windows)
    run = suite({"test_a": source})
    passed, skipped, failed = run.listoutcomes()
    assert (len(passed), len(skipped), len(failed)) == (0, 0, 1)
    assert str(failed[0].longrepr) == sentence


def test_a_test_without_the_windows_marker_still_skips_under_the_variable(suite, monkeypatch):
    monkeypatch.setenv("HMP_REQUIRE_WINDOWS", "1")
    run = suite({"test_a": "import pytest\n\ndef test_x():\n    pytest.skip('other reason')\n"})
    passed, skipped, failed = run.listoutcomes()
    assert (len(passed), len(skipped), len(failed)) == (0, 1, 0)


@pytest.mark.parametrize(
    ("filename", "source", "marked"),
    [
        (
            "test_terrain.py",
            "def test_x(request):\n    assert request.node.get_closest_marker('whitebox')\n"
            "    assert request.node.get_closest_marker('xdist_group').kwargs['name'] == 'whitebox_backend'\n",
            True,
        ),
        (
            "test_named_group.py",
            "import pytest\n\npytestmark = pytest.mark.xdist_group(name='whitebox_backend')\n\n"
            "def test_x(request):\n    assert request.node.get_closest_marker('whitebox')\n",
            True,
        ),
        (
            "test_other_file.py",
            "def test_x(request):\n    assert request.node.get_closest_marker('whitebox') is None\n"
            "    assert request.node.get_closest_marker('xdist_group') is None\n",
            False,
        ),
    ],
    ids=["listed file", "file that names the group", "other file"],
)
def test_the_whitebox_marker_follows_the_group(suite, filename, source, marked):
    run = suite({filename.removesuffix(".py"): source})
    passed, skipped, failed = run.listoutcomes()
    assert (len(passed), len(skipped), len(failed)) == (1, 0, 0), marked
