# solver/modflow6/api

`api_runner.py` drives a MODFLOW 6 workspace that is already written through the shared library `libmf6` and the optional `modflowapi` package, in place of the `mf6` executable. It calls a callback once per time step with an `Mf6ApiContext`, which reads and writes the lake stage and gives raw access to the other variables. A run takes this path when it must act between two steps, for example to pass the runoff of the exposed band of a lake back into the lake.
