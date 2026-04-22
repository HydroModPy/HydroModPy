from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Mapping


def run_pyhelp_simulation(
    run_pyhelp_func,
    workdir: Path,
    logger,
    climate_map: Mapping[str, str | Path] | None = None,
    *,
    fig_title: str = "PyHELP results",
    ymax=None,
    export_daily: bool = True,
):
    workdir.mkdir(parents=True, exist_ok=True)
    logger.info("[pyhelp] running simulation in %s", workdir)

    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            ret, diag = run_pyhelp_func(
                str(workdir),
                climate_map=climate_map,
                fig_title=fig_title,
                ymax=ymax,
                export_daily=export_daily,
            )
    except Exception as exc:
        logger.exception("[pyhelp] execution failed")
        ret, diag = 1, f"exception:{type(exc).__name__}"

    flush_external_logs(logger, buf)
    logger.info("[pyhelp] return_code=%s diag=%s", ret, diag)
    return ret, diag


def flush_external_logs(logger, buf: io.StringIO) -> None:
    for line in buf.getvalue().splitlines():
        if line.strip():
            logger.info("[pyhelp.ext] %s", line)
