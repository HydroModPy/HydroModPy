#!/usr/bin/env bash
# Smoke-test a few HydroModPy examples headless (no display, no browser).
# Used by .github/workflows/weekly-install-test.yml. Assumes the active
# environment already has HydroModPy installed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Neutralize interactive display calls so examples never block in CI.
SHIM="$(mktemp -d)"
cat > "$SHIM/sitecustomize.py" <<'PY'
import os
os.environ.setdefault("MPLBACKEND", "Agg")
try:
    import matplotlib
    matplotlib.use("Agg", force=True)
except Exception:
    pass
try:
    import matplotlib.pyplot as plt
    _orig = plt.show

    def _show(*a, **k):
        k["block"] = False
        try:
            return _orig(*a, **k)
        except TypeError:
            return _orig()

    plt.show = _show
except Exception:
    pass
try:
    import vedo
    _vshow = vedo.Plotter.show

    def _vedo_show(self, *a, **k):
        k["interactive"] = False
        return _vshow(self, *a, **k)

    vedo.Plotter.show = _vedo_show
except Exception:
    pass
try:
    import plotly.basedatatypes as _pbd
    _pbd.BaseFigure.show = lambda self, *a, **k: None
except Exception:
    pass
PY

export PYTHONPATH="$SHIM:${PYTHONPATH:-}"
export MPLBACKEND=Agg
export QT_QPA_PLATFORM=offscreen
export BROWSER=/bin/true

# Bundled solver binaries are tracked in git; make sure they are executable.
chmod +x bin/linux/* 2>/dev/null || true

# Fast, offline, non-interactive examples covering the core pipeline.
EXAMPLES=(
  "examples/11_for run from scratch without plots/example_11.py"
  "examples/00_quick_test_of_wide_hydromodpy_capabilities/example_00.py"
  "examples/07_analytical_solution_for_streamflow_recession/example_07.py"
)

rc_total=0
for rel in "${EXAMPLES[@]}"; do
  name="$(basename "$rel")"
  echo "::group::example $name"
  if timeout 900 python "$rel"; then
    echo "PASS $name"
  else
    rc=$?
    echo "::error::example $name failed (exit $rc)"
    rc_total=1
  fi
  echo "::endgroup::"
done

exit "$rc_total"
