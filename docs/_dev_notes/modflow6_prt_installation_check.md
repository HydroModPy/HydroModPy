# MODFLOW 6 PRT installation check

Date: 2026-05-15

Status: MODFLOW 6.7.0 Linux was installed in the WSL user area without deleting
the previous HydroModPy-managed binary. PRT support was checked from the local
distribution and from the official MODFLOW 6 documentation.

## Environment

- Repository path in WSL: `/mnt/c/codes/HydroModPy`.
- HydroModPy WSL Python: `/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python`.
- HydroModPy WSL Python version: `Python 3.13.12`.
- Default `python` on the WSL shell PATH: not found.
- Conda environments found include `base`, `hydromodpy-petsc`, and
  `hydromodpy-wsl` under `/home/dreuzy/miniforge3`.
- `~/.local/bin` was not relied on initially. The line below was added to
  `~/.bashrc` if absent:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Installed / Detected `mf6`

Previous HydroModPy cache binary kept in place:

- Path: `/home/dreuzy/.cache/hydromodpy/bin/mf6`.
- Version: `mf6: 6.6.3 09/29/2025`.

New user-level MODFLOW 6 binary:

- Source asset:
  `https://github.com/MODFLOW-ORG/modflow6/releases/download/6.7.0/mf6.7.0_linux.zip`.
- Install directory: `/home/dreuzy/.local/opt/modflow6/mf6_6.7.0`.
- Stable symlink: `/home/dreuzy/.local/opt/modflow6/mf6_latest`.
- Executable symlink: `/home/dreuzy/.local/bin/mf6`.
- `which mf6`: `/home/dreuzy/.local/bin/mf6`.
- Version: `mf6: 6.7.0 02/05/2026`.

Verification from `hydromodpy-wsl` Python with `PATH="$HOME/.local/bin:$PATH"`:

```text
mf6 from hydromodpy-wsl Python: /home/dreuzy/.local/bin/mf6
mf6: 6.7.0 02/05/2026
```

## PRT Verification

Local distribution scan found PRT examples and source files, including:

- `examples/ex-prt-mp7-p01/`;
- `examples/ex-prt-mp7-p03/`;
- `examples/ex-gwe-prt/`;
- `src/Model/ParticleTracking/prt.f90`;
- `src/Model/ParticleTracking/prt-prp.f90`;
- `src/Idm/prt-disidm.f90`;
- `src/Idm/prt-disvidm.f90`;
- `src/Idm/prt-prpidm.f90`;
- `src/Exchange/exg-gwfprt.f90`.

Local grep result:

- `GWF-PRT`: found in `src/Exchange/exg-gwfprt.f90`.
- `PRT-DIS`: not found as that exact uppercase text in local text files.
- `PRT-PRP`: not found as that exact uppercase text in local text files.

The local archive is still probative because it contains PRT examples and PRT
Fortran source/IDM files. The official online MODFLOW 6 input guide lists a
Particle Tracking section with `PRT-DIS`, `PRT-DISV`, `PRT-FMI`, `PRT-MIP`,
`PRT-NAM`, `PRT-OC`, `PRT-PRP`, and the model exchange `EXG-GWFPRT`.

Official references used:

- GitHub release: `https://github.com/MODFLOW-ORG/modflow6/releases/tag/6.7.0`.
- USGS release page: `https://www.usgs.gov/software/modflow-version-670`.
- Input guide: `https://modflow6.readthedocs.io/en/stable/mf6io.html`.
- PRT migration guide:
  `https://modflow6.readthedocs.io/en/6.6.3/_migration/mf6_6_0_prt_migration_guide.html`.

## HydroModPy Configuration

HydroModPy has two relevant paths:

1. Plain Python / FloPy PATH lookup sees `/home/dreuzy/.local/bin/mf6`.
2. HydroModPy solver construction normally resolves binaries through
   `hydromodpy.core.workspace.resolve_bin_path()`. Without an override, that
   points to the managed cache under `~/.cache/hydromodpy/bin`, which still
   contains MODFLOW 6.6.3.

The least invasive way to force a single run or TOML to use 6.7.0 is:

```toml
[modflow6.runtime]
mf6_executable_name = "/home/dreuzy/.local/bin/mf6"
```

For sessions where all HydroModPy MODFLOW binaries should be resolved from the
user directory, the environment override is:

```bash
export HYDROMODPY_BIN="$HOME/.local/bin"
```

This was not written globally to `~/.bashrc`, because it can affect other
MODFLOW-family executables (`mfnwt`, MT3D, etc.) if they are not also present in
`~/.local/bin`.

## Verification Script

Added:

- `scripts/check_modflow6_prt.py`

Run from WSL:

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /mnt/c/codes/HydroModPy
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python scripts/check_modflow6_prt.py --modflow6-home /home/dreuzy/.local/opt/modflow6/mf6_latest
```

Observed summary:

```text
mf6 executable: /home/dreuzy/.local/bin/mf6
version output:
mf6: 6.7.0 02/05/2026
PRT local files: found
GWF-PRT: found
```

## Light Checks

Executed:

```bash
python -m ruff check scripts/check_modflow6_prt.py
git diff --check -- scripts/check_modflow6_prt.py docs/_dev_notes/modflow6_prt_installation_check.md
```

Result:

```text
All checks passed.
```

Executed in WSL:

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /mnt/c/codes/HydroModPy
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest tests/unit/solver/test_modflow6_prt_contracts.py -q
```

Result:

```text
5 passed
```

## Commands Executed

```bash
pwd
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python --version
/home/dreuzy/miniforge3/bin/conda info --envs
which mf6 || true
mf6 -v || mf6 --version || mf6 || true
/home/dreuzy/.cache/hydromodpy/bin/mf6 -v
find /home/dreuzy/.cache/hydromodpy -maxdepth 4 \( -name mf6 -o -name mf6.exe \)
```

```bash
mkdir -p ~/.local/opt/modflow6 ~/.local/bin
cd ~/.local/opt/modflow6
wget -O mf6.7.0_linux.zip https://github.com/MODFLOW-ORG/modflow6/releases/download/6.7.0/mf6.7.0_linux.zip
/home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m zipfile -e mf6.7.0_linux.zip mf6_6.7.0
ln -sfn /home/dreuzy/.local/opt/modflow6/mf6_6.7.0 /home/dreuzy/.local/opt/modflow6/mf6_latest
ln -sf /home/dreuzy/.local/opt/modflow6/mf6_6.7.0/mf6.7.0_linux/bin/mf6 /home/dreuzy/.local/bin/mf6
```

```bash
find -L ~/.local/opt/modflow6/mf6_latest -iname "*prt*" | head -100
grep -R "GWF-PRT" ~/.local/opt/modflow6/mf6_6.7.0/mf6.7.0_linux/src 2>/dev/null | head -20
```

```bash
rg "mf6_executable_name|HYDROMODPY_BIN|mf6" hydromodpy examples tests -n
python scripts/check_modflow6_prt.py --modflow6-home /home/dreuzy/.local/opt/modflow6/mf6_latest
```

## Remaining Actions

- Run a real PRT model after the HydroModPy PRT workflow is ready for the target
  natural case.
- Use an explicit TOML path or `HYDROMODPY_BIN` when a HydroModPy run must use
  MODFLOW 6.7.0 instead of the managed 6.6.3 cache.
- Keep the old cache binary until all existing workflows have been checked
  against 6.7.0.
