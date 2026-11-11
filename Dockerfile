# Multi-stage build for HydroModPy.
# Stage 1 builds a wheel from the current source tree.
# Stage 2 is a slim runtime image that runs as a non-root user and exposes hmp.
# The server starts with: docker run --entrypoint python <image> -m hydromodpy_server
#   --root /project --host 0.0.0.0, with -e HMP_IMAGE_DIGEST=<digest>.

# ---- Stage 1: build wheel ---------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml MANIFEST.in README.md LICENSE ./
COPY hydromodpy ./hydromodpy
RUN pip install --no-cache-dir build \
    && python -m build --wheel --outdir /build/dist

# ---- Stage 2: runtime -------------------------------------------------------
FROM python:3.12-slim AS runtime

# The tag is the only identity the image can hold. The digest cannot be inside
# the image, so the operator passes it at start: docker run -e HMP_IMAGE_DIGEST=...
ARG HMP_IMAGE_TAG=dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/home/hmp/.local/bin:${PATH}" \
    HMP_IMAGE_TAG=${HMP_IMAGE_TAG}

# libglu1-mesa is needed by gmsh at import time.
# libexpat1 is needed by rasterio's runtime libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglu1-mesa libexpat1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r hmp \
    && useradd -r -g hmp -m -d /home/hmp -s /usr/sbin/nologin hmp \
    && mkdir -p /opt/hmp/bin /project \
    && chown -R hmp:hmp /opt/hmp /project

USER hmp
WORKDIR /home/hmp

# The wheel comes with every extra, so the image serves runs, calibration and
# the HTTP server alike. The solver binaries go to /opt/hmp/bin at build time.
# `hmp install-binaries` checks each one against the sha256 it pins.
ENV HMP_BIN=/opt/hmp/bin \
    PYTHONPATH=/opt/hmp

COPY --from=builder --chown=hmp:hmp /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir --user "$(ls /tmp/*.whl)[all]" \
    && rm /tmp/*.whl \
    && hmp install-binaries \
    && pip freeze > /opt/hmp/constraints.txt

COPY --chown=hmp:hmp hydromodpy_server /opt/hmp/hydromodpy_server

VOLUME /project
EXPOSE 8765

LABEL org.opencontainers.image.title="HydroModPy" \
      org.opencontainers.image.description="Catchment-scale shallow groundwater modeling toolbox" \
      org.opencontainers.image.source="https://github.com/HydroModPy/HydroModPy" \
      org.opencontainers.image.licenses="EPL-2.0"

HEALTHCHECK --interval=5m --timeout=15s --start-period=30s \
    CMD hmp doctor >/dev/null 2>&1 || exit 1

ENTRYPOINT ["hmp"]
CMD ["--help"]
