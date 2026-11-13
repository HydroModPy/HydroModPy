"""Validating a ``[display]`` section imports no frame module.

A fresh interpreter is the only honest viewer of frame-module imports: the
running display tree may have imported some already, and a subprocess is the
only way to see the first import reach them. The unit tier holds the
per-module checks; this holds the cross-tree one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_display_config_validates_without_importing_figure_modules() -> None:
    """Validating [display] sections must not import a frame or a special module."""
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from hydromodpy.display.config import DisplayConfig\n"
        "DisplayConfig.model_validate({'figure': [{'variable': 'head', 'time': 'last'}]})\n"
        "DisplayConfig.model_validate({'figure': [{'preset': 'hydrograph'}], 'theme': 'print'})\n"
        "imported = [m for m in sys.modules\n"
        "            if m.startswith(('hydromodpy.display.frames.', 'hydromodpy.display.special.'))]\n"
        "assert not imported, f'Modules imported: {imported}'\n"
        "print('OK')\n"
    )
    res = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert res.returncode == 0, f"Subprocess failed:\n{res.stderr}\n{res.stdout}"
    assert res.stdout.strip() == "OK"
