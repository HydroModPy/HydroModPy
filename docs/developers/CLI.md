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
hmp test regression --normal
hmp test regression --extensive
```

Run a specific one:

```bash
hmp test regression example12
hmp test regression launcher_simulation_normal --normal
```

Run only the extensive suite folder (or normal suite folder when populated):

```bash
hmp test regression --extensive
hmp test regression --normal
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
hmp test regression example12 -j 1   # single worker, useful for debugging
```

Update golden references (careful, this overwrites the expected outputs):

```bash
hmp test regression --update-goldens
hmp test regression example12 --update-goldens
```

### Notes

- The current regression set is: `launcher_simulation_normal` (normal), plus `example12_npy`, `launcher_simulation`, and `launcher_data_overview` (extensive).
- `--fast` and `--slow` match pytest markers, not individual examples.
- `--normal` and `--extensive` select tests by directory (`tests/regression/normal` and `tests/regression/extensive`).
- `-j` maps to pytest-xdist `-n` flag. Without it, tests run sequentially.
- The command prints the actual `pytest` invocation to stderr before running it.
