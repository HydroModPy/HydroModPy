"""The SFR Picard shortcut must not survive a mover feeding the reaches."""

from __future__ import annotations

from hydromodpy.solver.modflow6.builders.sfr import build_sfr_package_args


def _args(**definition):
    import inspect

    signature = inspect.signature(build_sfr_package_args)
    return signature, definition


def test_the_builder_reads_route_drainage_before_capping_picard():
    # The guard lives in the source, not behind a full model build: assert the
    # condition itself, so a refactor that drops `route_drainage` fails here.
    import inspect

    source = inspect.getsource(build_sfr_package_args)
    assert 'args["maximum_picard_iterations"] = 1' in source
    line = next(
        line for line in source.splitlines() if "downstream_increasing" in line and "if " in line
    )
    assert "route_drainage" in line, (
        "The one-Picard-pass shortcut assumes nothing moves water INTO the reaches. "
        "With route_drainage the DRN->SFR mover inflow updates once per outer "
        "iteration and the solution creeps instead of converging."
    )
