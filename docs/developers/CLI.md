# CLI usage

After `pip install -e .`, two commands are available: `hmp` and `hydromodpy`.
They do the same thing -pick whichever you prefer.

## Generate a config file

```bash
hmp config my_config.toml
hmp config my_config.toml --profile user
hmp config --list-modules
hmp config --modules flow transport
```

`--profile` controls how many parameters show up in the generated TOML:
- `user` -minimal, safe defaults
- `dev` -intermediate
- `expert` -everything (default)

## Run tests

### Unit tests

```bash
hmp test unit
```

### Regression tests

Run all of them:

```bash
hmp test regression
```

Filter by speed/tier:

```bash
hmp test regression --fast
hmp test regression --slow
hmp test regression --extensive
hmp test regression --nwt
hmp test regression --mf6
```

Run a specific one:

```bash
hmp test regression launcher_simulation_fast_nwt --fast --nwt
hmp test regression launcher_simulation_fast_mf6 --fast --mf6
hmp test regression launcher_simulation_extensive_nwt --extensive --nwt
hmp test regression launcher_simulation_extensive_mf6 --extensive --mf6
```

Run only one tier:

```bash
hmp test regression --fast
hmp test regression --extensive
```

See what's available:

```bash
hmp test regression --list
```

Parallel execution with `-j` (requires pytest-xdist):

```bash
hmp test regression -j auto          # use all CPU cores
hmp test regression --fast -j 4      # 4 workers
hmp test unit -j auto
hmp test regression launcher_simulation_extensive_nwt -j 1   # single worker, useful for debugging
```

Update golden references (careful, this overwrites the expected outputs):

```bash
hmp test regression --update-goldens
hmp test regression launcher_simulation_fast_mf6 --update-goldens
```

### Notes

- The current launcher regression set is: `launcher_simulation_fast_nwt`, `launcher_simulation_fast_mf6`, `launcher_simulation_extensive_nwt`, and `launcher_simulation_extensive_mf6`.
- `--fast` and `--extensive` select regression tiers; `--slow` remains a pytest marker filter.
- `--nwt` and `--mf6` filter regression tests by solver family.
- `--normal` is kept as a deprecated alias for `--fast`.
- `-j` maps to pytest-xdist `-n` flag. Without it, tests run sequentially.
- The command prints the actual `pytest` invocation to stderr before running it.
