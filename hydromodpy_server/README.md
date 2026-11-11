# hydromodpy_server

A thin HTTP layer on the verbs of HydroModPy, kept outside the wheel. It uses only the standard library and reads `hydromodpy`, `hydromodpy.core` and `hydromodpy.project`. Nothing in `hydromodpy` reads it.

Start it with `python -m hydromodpy_server --root ROOT`. The server has no authentication, so it sits behind a proxy that authenticates and gives each organisation its own path `/v1/<org>/`. Each organisation has one space `ROOT/<org>` and each study one project `ROOT/<org>/projects/<project>`. The server creates neither.

A verb is a POST to `/v1/<org>/<project>/<verb>` with its keyword arguments as a JSON object. The server fills `base`, `workspace`, `environment` and `headless`, and refuses them in the body. A path argument that is absolute or climbs with `..` is refused, and a call may write only under its project. `check`, `status`, `show`, `export` and the other short verbs answer in the request. `run`, `calibrate`, `spinup` and `replay` each start their own process and answer 202 with a job to read at `/v1/<org>/<project>/jobs/<job>`. `open` returns a live object, so it is not served. `example` and `doctor` are posted on `/v1/<org>`.

A file goes by `PUT /v1/<org>/<project>/inputs/<name>`. It is written under `inputs/` as `<sha256[:8]>_<name>` through `ROOT/.inbox/`, so the same bytes give the same file.

The server warms `check` with `warm.json` before it prints `serving on http://<host>:<port>`. The start takes 3 to 6 s and a child process is ready in about 3 s. After the warm-up a `check` of a full document of example 04 takes about 8 ms at the median inside the process, and the first one at most 19 ms. The HTTP round trip adds the JSON of the document. In a container image the server refuses to start without `HMP_IMAGE_DIGEST`, so each run seals the image it ran in.
