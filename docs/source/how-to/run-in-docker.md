# Run in Docker

The `Dockerfile` of the repository builds a slim image whose entry point is `hmp`, so a container
runs the same program as the command line. The image holds HydroModPy with every extra, the
solver binaries, which `hmp install-binaries` fetched under `/opt/hmp/bin` at the build and
checked against their pinned sha256, and the HTTP server of the repository. The versions of the
build are kept in `/opt/hmp/constraints.txt`. Each version tag publishes the image on the GitHub
container registry, tagged with the version, and as `latest` when the version is not a
pre-release. Pull it by its tag:

```bash
docker pull ghcr.io/hydromodpy/hydromodpy:2.0.0
docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/hydromodpy/hydromodpy:2.0.0
```

The second command prints the image name, `@` and its digest, `sha256:` followed by 64 hex
characters. Or build the image from a clone, with the tag you give it:

```bash
docker build --build-arg HMP_IMAGE_TAG=2.0.0 -t hydromodpy:2.0.0 .
```

A run request is one JSON file that holds the configuration under `config`. A container plays it
from a project folder you mount, and `--base` names the folder its relative paths are read from:

```bash
docker run --rm -v "$PWD/project:/project" hydromodpy:2.0.0 run /project/request.json --base /project
```

The run folder, `request.json` included, is written under `/project/runs/`. The request itself
is described in {doc}`../contribute/architecture/how-to/build-a-frontend`. An image cannot hold its
own digest, so pass it with `-e HMP_IMAGE_DIGEST=sha256:<digest>`. For a pulled image, take the
part after `@` of the `RepoDigests` line above. For an image built here,
`docker inspect --format '{{.Id}}' hydromodpy:2.0.0` gives it. A run then writes the tag
and the digest of the image in its `provenance.json`. A replay of the run with
`hmp replay <run> --strict` gives the same numbers to the bit only in the same image, on the same
family of processor and with the number of BLAS threads fixed, for example with
`-e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1`. The CI plays such a replay in each image it
builds. The server needs the digest to start:

```bash
docker run -d --hostname hmp-server -p 8765:8765 -v /srv/hmp:/project \
  -e HMP_IMAGE_DIGEST=sha256:<digest> \
  --entrypoint python hydromodpy:2.0.0 -m hydromodpy_server --root /project --host 0.0.0.0
```

{doc}`../contribute/architecture/how-to/serve-over-http` describes its routes.
