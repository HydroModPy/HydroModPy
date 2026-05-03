# Security Policy

## Supported Versions

HydroModPy follows a rolling "current minor + previous minor" policy.
The current minor receives both bug fixes and security fixes; the
previous minor receives security fixes only. Older minors (including
pre-release tags) are not patched.

| Version | Supported              |
| ------- | ---------------------- |
| 1.0.x   | :white_check_mark:     |
| 0.5.x   | security fixes only    |
| < 0.5   | :x:                    |

## Threat Model

HydroModPy targets a **trusted single-tenant scientific desktop**:

- A single researcher (or a tightly coordinated team) installs the
  package in their own conda / venv environment.
- The workspace directory (`hydromodpy.duckdb`, Zarr stores, Parquet
  outputs, `.hmp/checkpoints/`, downloaded MODFLOW binaries) is owned
  and controlled by that researcher.
- Configuration TOML files, calibration inputs, and project scripts
  under `examples/projects/` are authored or reviewed by the same
  researcher.
- Public scientific HTTP APIs (Hub'Eau, SHOM, IGN BD ALTI, GeoSAS SIM2)
  are reached over TLS with system-trusted certificates.

The assets we protect under this model are:

1. The integrity of the user's research workspace (no silent corruption
   of catalogs, checkpoints, or simulation outputs).
2. The integrity of the install (no remote-code-execution path through
   `pip install hydromodpy`, the published wheel, or the published
   Docker image).
3. The supply chain of binary solver dependencies (MODFLOW 6,
   MODFLOW-NWT) downloaded lazily by `hmp install-binaries`.

Threats explicitly **in scope**:

- Remote code execution via a malicious wheel / sdist published under
  the `hydromodpy` PyPI name.
- Remote code execution via a tampered Docker image published under the
  project's container registry.
- Supply-chain compromise of pinned runtime dependencies (we pin upper
  bounds in `pyproject.toml`; advisories trigger a patch release).
- Path traversal through user-facing CLI arguments that could escape
  the workspace root and write outside it.
- Credential leakage in logs, traces, or telemetry (HydroModPy ships
  no telemetry).

Threats explicitly **out of scope**:

- Attacks that require an attacker to first place a malicious file
  inside the user's workspace (e.g., a poisoned
  `.hmp/checkpoints/*.pkl`, a hostile `id_particles_random` MODPATH
  pickle, a crafted Parquet/Zarr store). The workspace is trusted by
  assumption; deserialising files under it is treated like loading a
  local Python module.
- Attacks on multi-tenant deployments (shared HPC scratch directories,
  shared workspaces between mutually distrusting users, public web
  services that expose HydroModPy as a backend). HydroModPy is not
  hardened for these scenarios; do not deploy it that way.
- Denial-of-service against the user's own machine (a long simulation,
  an accidental fork bomb in a user-supplied project script, a
  pathological mesh).
- Bugs in upstream solvers (MODFLOW 6, MODFLOW-NWT, PETSc) or in
  scientific HTTP API providers. Report these upstream.
- Physical / local-attacker scenarios (someone with shell access to the
  workspace machine).

## Reporting a Vulnerability

**Do not open a public GitHub issue for a suspected vulnerability.**

Preferred channel: open a private security advisory at
<https://github.com/HydroModPy/HydroModPy/security/advisories/new>.

Backup channel (if the advisory form is unavailable): email
`alexandre.gauvain.ag@gmail.com` and `bastien.boivin@proton.me` with
subject `[hydromodpy security]` and a description of the issue, a
reproduction recipe, and the affected version.

Please include:

- HydroModPy version (`hmp --version` or `pip show hydromodpy`).
- Python version and OS.
- Whether MODFLOW solver binaries are involved.
- A minimal reproduction (config TOML, script, or workflow).
- Your assessment of impact under the threat model above.

## Disclosure Timeline

We follow a **90-day coordinated disclosure** window:

| Day | Step |
|-----|------|
| 0   | Maintainers acknowledge receipt (target: 5 working days). |
| 0–30 | Triage, severity assessment, fix design. |
| 30–60 | Fix implemented on a private branch, regression tests added. |
| 60–90 | Patch release prepared; reporter reviews fix and advisory text. |
| 90  | Coordinated public disclosure: patch release tagged, GitHub Security Advisory published, CHANGELOG entry under `### Security`. |

If the vulnerability is being actively exploited, we cut the timeline
short and ship a patch release immediately.

If we have not acknowledged receipt within 10 working days, the
reporter is free to disclose publicly.

## Hardening Notes for Operators

Even within the trusted-desktop model, we recommend:

- Install HydroModPy in a dedicated conda or venv environment, never as
  root / Administrator.
- Treat `<workspace>/.hmp/checkpoints/` and any `*.pkl` produced by
  MODPATH as code: do not unpickle checkpoints obtained from another
  user without inspecting them first.
- Verify the SHA-256 of solver binaries fetched by
  `hmp install-binaries` against the published lockfile
  (`hydromodpy.lock`).
- Pin the HydroModPy version in your project (`pyproject.toml` or
  `requirements.txt`) and review CHANGELOG entries under `### Security`
  before upgrading.

## Acknowledgements

Reporters who follow this policy will be credited in the published
GitHub Security Advisory and in the corresponding CHANGELOG entry,
unless they request anonymity.
