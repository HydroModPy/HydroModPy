"""What the five ``test_*_conformance_reaches_an_installed_*`` files share.

Each one unpacks a distribution beside the build (a module and its ``.dist-info``,
what a wheel unpacks to, with no build and no network) and runs a conformance suite
on it in a child interpreter. ``importlib.metadata`` reads the entry points once and
the registries cache them, so a plugin installed inside a running interpreter would
be a different experiment from the one a third party performs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def unpack(root: Path, module: str, text: str, group: str, entry_id: str, entry_class: str) -> Path:
    """Write ``module.py`` and a ``.dist-info`` that publishes *entry_class* in *group*."""
    (root / f"{module}.py").write_text(text, encoding="utf-8")
    dist_info = root / f"{module}-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {module.replace('_', '-')}\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        f"[{group}]\n{entry_id} = {module}:{entry_class}\n", encoding="utf-8"
    )
    return root


def run_suite(
    suite: str, session: Path, *arguments: str, site_packages: Path | None = None
) -> subprocess.CompletedProcess:
    """Run pytest on *suite* in a child interpreter, with or without the probe installed.

    *session* is the child's own unused ``--basetemp``, so parent and child share no
    temp root, and the cache plugin is off so they share no ``.pytest_cache``. The
    child is a plain session, not an xdist worker of the parent.
    """
    environment = dict(os.environ)
    environment.pop("PYTEST_XDIST_WORKER", None)
    entries = [site_packages, REPO_ROOT, environment.get("PYTHONPATH")]
    environment["PYTHONPATH"] = os.pathsep.join(str(entry) for entry in entries if entry)
    return subprocess.run(
        [sys.executable, "-m", "pytest", suite, "-p", "no:randomly", "-p", "no:cacheprovider",
         f"--basetemp={session}", *arguments],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=900,
    )  # fmt: skip


def collected(output: str, suite: str, entry_id: str = "") -> list[str]:
    """The node ids of *suite* in a ``--collect-only -q`` output, of *entry_id* only when given."""
    return [line for line in output.splitlines() if line.startswith(suite) and entry_id in line]
