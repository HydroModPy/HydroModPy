"""SFR figures rendered from the REAL synthetic-Cheze E2E store.

One ``hmp run`` of the committed valley fixture (the same production pipeline as
``tests/e2e/test_sfr_cheze_e2e.py``) populates a real catalog; the three SFR
figures are then rendered through the ``Run`` interface and checked for actual
drawn content. The display call must write nothing (the read-only contract from
``tests/unit/display/test_display_never_writes_zarr.py``): the catalog tree is
fingerprinted before and after rendering.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    _open_result_store,
    _resolve_sim_id,
    assert_required_executables,
    run_hmp_cli,
)


def _tree_fingerprint(root: Path) -> dict[str, float]:
    return {
        str(path.relative_to(root)): path.stat().st_mtime_ns
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".duckdb" not in path.name
    }


@pytest.fixture(scope="module")
def sfr_run(tmp_path_factory):
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    from tests.e2e.test_sfr_cheze_e2e import _config_body

    out_path = tmp_path_factory.mktemp("sfr_figures")
    config_path = out_path / "run_sfr_figures.toml"
    config_path.write_text(_config_body(with_sfr=True), encoding="utf-8")
    run_hmp_cli(config_path=config_path, out_path=out_path, timeout=2400)
    return out_path


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_sfr_figures_render_from_the_real_store(sfr_run: Path, tmp_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")

    from hydromodpy.display.catalog import get as get_figure
    from hydromodpy.results.run import Run

    store = _open_result_store(sfr_run)
    try:
        sim_id = _resolve_sim_id(store)
        run = Run(sim_id, store)
        simulations_dir = sfr_run / "simulations"
        before = _tree_fingerprint(simulations_dir)

        for name, opts in (
            ("sfr_reach_timeseries", {}),
            ("sfr_longitudinal_profile", {}),
            ("sfr_reach_network", {}),
        ):
            figure = get_figure(name)
            save_path = tmp_path / f"{name}.png"
            mpl_figure = figure.plot(run, save_path=save_path, **opts)

            axes = mpl_figure.get_axes()
            assert len(axes) >= 1, f"{name}: figure has no axes"
            target = axes[0]
            drawn = list(target.lines) + list(target.collections)
            assert drawn, f"{name}: nothing drawn on the target axes"
            if target.lines:
                assert len(target.lines[0].get_xdata()) > 0, f"{name}: empty line data"
            assert save_path.is_file(), f"{name}: PNG not written"
            assert save_path.stat().st_size > 4096, f"{name}: PNG suspiciously small"

            import matplotlib.pyplot as plt

            plt.close(mpl_figure)

        # Read-only contract: rendering wrote NOTHING into the store tree.
        after = _tree_fingerprint(simulations_dir)
        assert after == before, "display rendering modified the store tree"
    finally:
        store.close()


@pytest.mark.integration
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_sfr_longitudinal_profile_accumulates_downstream(sfr_run: Path) -> None:
    from hydromodpy.results.run import Run

    store = _open_result_store(sfr_run)
    try:
        sim_id = _resolve_sim_id(store)
        run = Run(sim_id, store)
        from hydromodpy.display.figures.sfr_reach_timeseries import sfr_reach_stations

        triples = sfr_reach_stations(run, "downstream_flow")
        assert len(triples) >= 3, "expected a multi-reach network"
        flows = [
            float(run.timeseries("downstream_flow", station=s).iloc[-1]) for _, _, s in triples
        ]
        # The routed flow grows along the main stem: the terminal reach carries
        # more than the headwater reach.
        assert flows[-1] > flows[0]
    finally:
        store.close()
