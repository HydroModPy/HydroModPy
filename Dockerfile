# Multi-stage build for HydroModPy.
# Stage 1 builds a wheel from the current source tree.
# Stage 2 is a slim runtime image that runs as a non-root user and exposes hmp.

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

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/home/hmp/.local/bin:${PATH}"

# libglu1-mesa is needed by gmsh / pyvista at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglu1-mesa \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r hmp \
    && useradd -r -g hmp -m -d /home/hmp -s /usr/sbin/nologin hmp

USER hmp
WORKDIR /home/hmp

COPY --from=builder --chown=hmp:hmp /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir --user /tmp/*.whl \
    && rm /tmp/*.whl

# Solver binaries (mf6, mfnwt, ...) are not shipped in the image.
# They are downloaded lazily on first solver run into ~/.cache/hydromodpy/bin/,
# or eagerly via `hmp install-binaries`.

LABEL org.opencontainers.image.title="HydroModPy" \
      org.opencontainers.image.description="Catchment-scale shallow groundwater modeling toolbox" \
      org.opencontainers.image.source="https://github.com/HydroModPy/HydroModPy" \
      org.opencontainers.image.licenses="EPL-2.0"

HEALTHCHECK --interval=5m --timeout=15s --start-period=30s \
    CMD hmp doctor >/dev/null 2>&1 || exit 1

ENTRYPOINT ["hmp"]
CMD ["--help"]
