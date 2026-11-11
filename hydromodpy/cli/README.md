# cli

The command line, with the `hmp` and `hydromodpy` entry points. It parses arguments, calls the code that does the work, formats the output and turns an exception into a typed exit code. It holds no scientific logic, so a result that the command line gives is the one that `hydromodpy.project.api` gives.

The top-level commands follow the order of `ALL_COMMANDS`. A command is one module of `commands/`, or one sub-package for a family of actions such as `catalog` or `data`. Each exposes `NAME`, `HELP`, `register` and `run`. `conventions.py` holds the shared argparse grammar, `output.py` the one way a command writes JSON or CSV for a program, and `exit_codes.py` the map from an exception category to an exit code, which is 1, 2 or 10 to 23, with 130 for an interruption.

`cli` sits above the layer matrix. It reads every package below it, and only the entry point `hydromodpy/__main__.py` reads it. `hmp <verb> --help` prints the options of each verb, and the CLI reference of the docs is generated from the same parsers.

The page of the package in the developer docs lists the modules, gives which command calls which verb, tells how a run starts and says where to add a command.
