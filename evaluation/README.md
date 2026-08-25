# Evaluation

This folder contains standalone scripts for measuring the structure and quality of a Python repository.

For the exact formula behind every metric, what the numbers mean, and the limitations found while using them on this codebase, see [METRICS.md](METRICS.md).

## Available scripts

- `extract_architecture.py` extracts classes, functions, modules, internal dependencies, and an architecture graph.
- `radon_metrics.py` computes cyclomatic complexity, Maintainability Index, and Halstead metrics.
- `coupling.py` computes a simplified CBO coupling score, split into efferent (`efferent_coupling`, outgoing — what the class depends on) and afferent (`afferent_coupling`, incoming — what depends on the class) counts. A facade/orchestrator is expected to have high efferent and low afferent coupling; a class with both high is a stronger signal of a real problem than either number alone.
- `cohesion.py` computes an approximate LCOM cohesion score. `lcom` is `None` (not just a misleadingly perfect 0.0) for classes where the metric does not apply: dataclasses, Pydantic models, `Protocol`s, `Mixin`s, and thin facades (see `kind` below).
- `duplication.py` finds near-duplicate functions/methods (same logic after stripping formatting and renaming local identifiers) that CBO/LCOM cannot see — a real maintenance risk, since a fix applied to one copy can silently miss the others.
- `reliability.py` approximates a SonarQube-style "Reliability" signal (bug-pattern detection, as opposed to the design-quality metrics above) by running Ruff's pyflakes (`F`) and flake8-bugbear (`B`) rule families and reporting a simple A–E rating. It does not override the project's own `pyproject.toml` `[tool.ruff.lint]` select/ignore config, so it keeps respecting deliberate exceptions (e.g. the `B008` tolerance for Pydantic `Field(...)` defaults) — only the resulting violations are filtered to the F/B subset afterwards. This is not a reimplementation of SonarQube's proprietary engine, just a complementary, already-available signal for the same idea.
- `repository_summary.py` generates a repository-wide summary.
- `compare_repositories.py` compares two repositories or two prepared reports and generates comparison charts.
- `generate_report.py` aggregates the outputs and produces CSV, Excel, and charts.
- `run_all.py` runs the full workflow in one command and writes everything to a user-defined output folder.

## Reading coupling/cohesion numbers in context

Both `coupling.py` and `cohesion.py` tag every class with a `kind`: `"dataclass"`, `"model"` (Pydantic/NamedTuple), `"protocol"`, `"mixin"`, `"facade"` (every method just forwards to another callable), or `"business-logic"`. A raw CBO or LCOM number means something different depending on `kind` — a facade is *supposed* to have high coupling, a Pydantic model is *supposed* to have "low" cohesion by this metric. Filter or group by `kind` before ranking classes as "worst offenders", otherwise the ranking will mostly surface intentional design rather than real problems.

## Requirements

Optional dependencies used by the evaluation scripts:

- `radon`
- `networkx`
- `pandas`
- `matplotlib`
- `openpyxl`

## Commands

Use `--root` when the repository is already available locally.
Use `--repo` and `--branch` when you want the script to clone a remote repository first.
If the repository is already cloned internally, pass only the local path with `--root`.

If you want to run everything at once, use `run_all.py` and choose the output folder with `--output-dir`.

Examples:

- Local repository already cloned:

```bash
python3 evaluation/repository_summary.py --root /home/amine/HydroModPy-Hackathon
```

- Remote repository to clone on demand:

```bash
python3 evaluation/repository_summary.py \
	--repo https://github.com/ORG/REPO.git \
	--branch main
```

### 1. Repository summary

```bash
python3 evaluation/repository_summary.py \
	--root . \
	--output evaluation/out/summary.json \
	--csv evaluation/out/summary.csv
```

From a remote repository:

```bash
python3 evaluation/repository_summary.py \
	--repo https://github.com/ORG/REPO.git \
	--branch main \
	--output evaluation/out/summary.json \
	--csv evaluation/out/summary.csv
```

### 2. Radon metrics

```bash
python3 evaluation/radon_metrics.py \
	--root . \
	--output evaluation/out/radon.json
```

From a remote repository:

```bash
python3 evaluation/radon_metrics.py \
	--repo https://github.com/ORG/REPO.git \
	--branch main \
	--output evaluation/out/radon.json
```

### 3. Coupling

```bash
python3 evaluation/coupling.py \
	--root . \
	--output evaluation/out/coupling.json
```

### 4. Cohesion

```bash
python3 evaluation/cohesion.py \
	--root . \
	--output evaluation/out/cohesion.json
```

### 5. Architecture extraction and graph

```bash
python3 evaluation/extract_architecture.py \
	--root . \
	--output evaluation/out/architecture.json \
	--graph-output evaluation/out/architecture_graph.png
```

You can also export the architecture graph as GraphML or JSON by changing the file extension of `--graph-output`.

### 6. Generate the full report

If you already have JSON outputs in one folder:

```bash
python3 evaluation/generate_report.py \
	--input-dir evaluation/out \
	--output-dir evaluation/report \
	--excel evaluation/report/evaluation.xlsx
```

Directly from a remote repository:

```bash
python3 evaluation/generate_report.py \
	--repo https://github.com/ORG/REPO.git \
	--branch main \
	--output-dir evaluation/report \
	--excel evaluation/report/evaluation.xlsx
```

### 7. Run everything in one command

For a repository that is already cloned locally:

```bash
python3 evaluation/run_all.py \
	--root /home/amine/HydroModPy-Hackathon \
	--output-dir /home/amine/HydroModPy-Hackathon/hackathon
```

For a remote repository:

```bash
python3 evaluation/run_all.py \
	--repo https://github.com/ORG/REPO.git \
	--branch main \
	--output-dir /home/amine/HydroModPy-Hackathon/hackathon
```

This creates:

- `/output-dir/raw/` with the JSON outputs and the architecture graph.
- `/output-dir/report/` with CSV files and charts.
- `/output-dir/evaluation.xlsx` with the Excel report.

### 7. Compare two repositories

Generate a JSON comparison and the main bar chart:

```bash
python3 evaluation/compare_repositories.py \
	--left-repo https://github.com/ORG/REPO-A.git --left-branch main \
	--right-repo https://github.com/ORG/REPO-B.git --right-branch develop \
	--output evaluation/out/comparison.json \
	--chart evaluation/out/comparison_bar_chart.png
```

Generate the complete comparison bundle with all requested charts:

```bash
python3 evaluation/compare_repositories.py \
	--left-repo https://github.com/ORG/REPO-A.git --left-branch main \
	--right-repo https://github.com/ORG/REPO-B.git --right-branch develop \
	--left-label hackathon \
	--right-label legacy \
	--output evaluation/out/comparison.json \
	--output-dir evaluation/out/charts
```

You can use `--left-label` and `--right-label` to force the names shown in the charts.

This will generate:

- `bar_chart.png` for direct metric comparison.
- `boxplot_complexity.png` for the cyclomatic complexity distribution.
- `radar_chart.png` for Complexity, Maintainability, CBO, LCOM, and Halstead.
- `dependency_heatmap.png` for module dependencies.
- `architecture_graph.png` for the NetworkX architecture graph.

## Typical workflow

### Execution order

Run the scripts in this order when you want a complete analysis of one repository:

1. `repository_summary.py` to collect the basic repository structure.
2. `radon_metrics.py` to compute complexity, Maintainability Index, and Halstead.
3. `coupling.py` to compute the CBO coupling score.
4. `cohesion.py` to compute the LCOM approximation.
5. `extract_architecture.py` to build the architecture data and graph.
6. `generate_report.py` to aggregate the results and create CSV, Excel, and charts.

When comparing two repositories, run:

1. `compare_repositories.py` if you already have two repositories or two summary files.
2. `generate_report.py` if you want a complete report folder for one repository.

```bash
mkdir -p evaluation/out evaluation/report
python3 evaluation/repository_summary.py --root . --output evaluation/out/summary.json --csv evaluation/out/summary.csv
python3 evaluation/radon_metrics.py --root . --output evaluation/out/radon.json
python3 evaluation/coupling.py --root . --output evaluation/out/coupling.json
python3 evaluation/cohesion.py --root . --output evaluation/out/cohesion.json
python3 evaluation/extract_architecture.py --root . --output evaluation/out/architecture.json --graph-output evaluation/out/architecture_graph.png
python3 evaluation/generate_report.py --input-dir evaluation/out --output-dir evaluation/report --excel evaluation/report/evaluation.xlsx
```
