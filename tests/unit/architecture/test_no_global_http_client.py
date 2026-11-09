"""Architecture gate: no global HTTP client, ad-hoc session or urllib in hydromodpy.

Every remote asset and user URL downloaded by HydroModPy passes through
``hydromodpy.core.io.fetch``. Ad-hoc ``requests.Session()``, ``get_default_client``,
and stdlib ``urllib.request.(urlopen|urlretrieve)`` outside of ``core/io/fetch.py``
violate ARCH 4 and rule 15.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PKG_ROOT = REPO_ROOT / "hydromodpy"
FETCH_PY = PKG_ROOT / "core" / "io" / "fetch.py"

FORBIDDEN_PATTERNS = (
    (re.compile(r"\bget_default_client\b"), "get_default_client"),
    (re.compile(r"requests\.Session\("), "requests.Session("),
    (re.compile(r"urllib\.request\.(urlopen|urlretrieve)"), "urllib.request.(urlopen|urlretrieve)"),
)


def test_no_global_http_client_or_unfenced_sessions() -> None:
    """hydromodpy/ outside fetch.py must not create sessions, singletons, or call urllib."""
    violations: list[str] = []

    for path in PKG_ROOT.rglob("*.py"):
        if path == FETCH_PY:
            continue
        rel = path.relative_to(REPO_ROOT)
        content = path.read_text(encoding="utf-8")
        for pattern, label in FORBIDDEN_PATTERNS:
            matches = list(pattern.finditer(content))
            for m in matches:
                lineno = content.count("\n", 0, m.start()) + 1
                violations.append(f"{rel}:{lineno}: matches forbidden pattern {label!r}")

    assert not violations, (
        f"Found {len(violations)} forbidden HTTP client / session / urllib usage(s):\n"
        + "\n".join(violations)
    )
