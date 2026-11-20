"""Child entry point: run one Whitebox depression tool from file to file.

Run by path, never imported. It imports nothing from HydroModPy, so the child
interpreter starts in tens of milliseconds. Arguments, in order: the tool name,
the source raster, the target raster, the tool options as JSON, the worker
count and ``1`` or ``0`` for Whitebox's own logging.
"""

import json
import sys

import whitebox_workflows as wbw


def main(argv: list[str]) -> None:
    """Read the source, run the tool, write the target."""
    tool, source, target, options, max_procs, verbose = argv[1:7]
    env = wbw.WbEnvironment()
    env.verbose = verbose == "1"
    env.max_procs = int(max_procs)
    result = getattr(env, tool)(env.read_raster(source), **json.loads(options))
    env.write_raster(result, target, compress=False)


if __name__ == "__main__":
    main(sys.argv)
