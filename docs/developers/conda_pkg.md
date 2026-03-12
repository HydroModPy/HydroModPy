# HydroModPy: Conda-Forge Packaging Memo

**Context:** Packaging a library sourced from PyPI that vendors upstream binaries (MODFLOW executables) in `bin/`. Requires specific handling to bypass standard Conda linking checks and CI network restrictions.

## 1. Repository Structure

In the `staged-recipes` fork, the directory must be:
`recipes/hydromodpy/`

Required files:
1.  `meta.yaml` (Package definition)
2.  `conda_build_config.yaml` (Build matrix configuration)

## 2. `meta.yaml` Configuration

**Source**
* Use `url` pointing to the PyPI `.tar.gz` file.
* Use `sha256` checksum.
* Do not use `git_url`.

**Binary Handling (Critical)**
The package ships pre-compiled executables (`mf6`, `mfnwt`, `mp6`, `mt3dusgs`) in `bin/`. Standard Conda build tries to patch RPATHs and verify system links (`libc`), which causes failures.
* **`binary_relocation: false`**: Tells Conda not to modify the executables.
* **`missing_dso_whitelist: - "*"`**: Tells the linter to ignore "OverLinkingError" (missing links to system libraries).

**Dependencies & Linter Compliance**
* **Python Version**: Use `skip: true # [py<311]` in the `build` section. Do not pin versions in `host`/`run` (just list `python`).
* **Syntax**: Use `python >=3.11` (no space after operator).
* **Matplotlib**: Depend on `matplotlib-base` to avoid pulling heavy Qt dependencies.
* **License**: Path must be `LICENSE` (root of tarball), not `../LICENSE`.

**Testing (`whitebox-workflows`)**
HydroModPy now depends on `whitebox-workflows` instead of the legacy `whitebox`
package. No binary download workaround or `WBT_PATH` injection is required at
import time.
* **Command**: `python -c "import hydromodpy; print(hydromodpy.__version__)"`

## 3. Build Matrix (`conda_build_config.yaml`)

Standard configuration fails on Windows/macOS due to ambiguous Python pinning. We must define the matrix explicitly using `zip_keys`.

**File content:**
```yaml
python:
  - 3.11.* *_cpython
  - 3.12.* *_cpython
  - 3.13.* *_cp313
is_python_min:
  - true
  - false
  - false
zip_keys:
  - - python
    - is_python_min
channel_targets:
  - conda-forge main
```

## 4\. Local Validation

Always validate locally to check whitelist logic before pushing.

1.  **Build:**
    `conda mambabuild recipes/hydromodpy -c conda-forge`
2.  **Test:**
    `conda create -n test-env --use-local hydromodpy`

## 5\. Submission Process

1.  Fork `conda-forge/staged-recipes`.
2.  Push `recipes/hydromodpy` to a new branch.
3.  Open Pull Request against `main`.
4.  **Justification**: Post a comment explaining the binaries.
      * "We vendor upstream MODFLOW executables to ensure out-of-the-box functionality. This requires `binary_relocation: false` and the `missing_dso_whitelist`."
5.  **Review**: Trigger the Python team for faster review.
      * Comment: `@conda-forge-admin, please ping conda-forge/help-python`

## 6\. Maintenance (Feedstock) - in process ...

  * Once merged, `hydromodpy-feedstock` is created automatically.
  * **Updates**: The Conda-Forge bot detects PyPI releases and opens PRs on the feedstock.
  * **Workflow**: Verify version/hash in the bot PR, then merge.
