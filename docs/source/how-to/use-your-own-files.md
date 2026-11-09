# Use your own files

HydroModPy reads elevation models, hydrography, geology, structures, forcings
and observation series from public APIs or from files on disk. When I bring my
own data, I place the files under the `inputs/` folder of my project and
declare them in the project configuration.

## Where files sit

I store local data files under `<project>/inputs/`. Paths written in the
configuration are relative to the project root, so they remain valid when the
project moves or when I share it with a collaborator.

For example, a digital elevation model in `inputs/elevation.tif` is declared
with `path = "inputs/elevation.tif"`.

HydroModPy resolves relative paths against the project root only. A bare file
name such as `path = "elevation.tif"` is no longer looked up in the data
folders of the workspace. When a bare name is not found directly at the project
root, the run stops with an error message that points to the former search path
and suggests moving the file to `inputs/`.

A path cannot start with a URL scheme such as `https://`. When data reside on
a remote server, I declare them with `source = "url"` instead.

## The `file` source

Local files are declared with `source = "file"`. This source replaces the
earlier `source = "custom"` and works for rasters, vector layers, tabular
data and station chronicle folders.

```toml
[[data.dem.sources]]
source = "file"
path = "inputs/elevation.tif"
```

The `file` source reads files directly from disk without copying them into the
data cache. Before the run begins, HydroModPy calculates the SHA-256 digest of
each input file to record its provenance in the run manifest and seal.

If an older configuration still writes `source = "custom"`, `hmp doctor --fix-config`
rewrites it to `source = "file"`.

## The `url` source

When a file is hosted online, I can declare it directly with `source = "url"`.
The `url` source applies to variables that are read from a single file, such as
digital elevation models, geology rasters or vectors, stream networks, structures,
and single-file climate grids.

```toml
[[data.dem.sources]]
source = "url"
url = "https://example.org/data/dem.tif"
sha256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
```

The URL source downloads the remote file once into the local data cache under
`data/<variable>/` and creates an accompanying JSON sidecar. The simulation run
then reads the cached file in the same way as a local `file` source.

HTTPS is accepted directly. An unencrypted HTTP URL is accepted only when I pin
its expected SHA-256 digest with the `sha256` parameter.

When a download is already cached, HydroModPy sends a HEAD request to check the
remote ETag and Last-Modified headers before downloading again. If the headers
match, or if the pinned SHA-256 digest is already present in the cache, the
cached file is reused without downloading.

Network downloads are constrained by execution bounds. The default byte limit
is 2 GiB. Private network IP addresses are refused unless the host is
explicitly permitted with the `--allow-host` command-line flag or the execution
environment.

## Elevation model declaration

In earlier versions, a digital elevation model was declared through
`dem_init_path` under `[geographic.catchment]`. This parameter has been removed.

The elevation model is now declared under `[[data.dem.sources]]` with
`source = "file"` or `source = "url"`.

```toml
[[data.dem.sources]]
source = "file"
path = "inputs/dem.tif"
```

The pre-processing pipeline resolves the digital elevation model from this
table and passes the resolved path to the catchment delineation steps.
