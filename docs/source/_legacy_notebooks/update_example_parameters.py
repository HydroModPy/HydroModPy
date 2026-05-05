from __future__ import annotations

import ast
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nbformat as nbf
from nbformat.validator import normalize

NOTEBOOK_DIR = Path(__file__).resolve().parent
REPO_ROOT = NOTEBOOK_DIR.parents[3]

NOTEBOOK_SOURCE_MAP = {
    "example_00": "examples_legacy/00_quick_test_of_wide_hydromodpy_capabilities/example_00.py",
    "example_01": "examples_legacy/01_simplified_example_presented_in_the_paper/example_01.py",
    "example_02": "examples_legacy/02_basic_features_and_overview_of_possibilities/example_02.py",
    "example_03": "examples_legacy/03_hydrographic_network_in_steady_state/example_03.py",
    "example_04": "examples_legacy/04_streamflow_intermittence_in_transient/example_04.py",
    "example_05": "examples_legacy/05_piezometry_in_a_heterogeneous_coastal_aquifer/example_05.py",
    "example_06": "examples_legacy/06_particle_tracking_and_residence_times/example_06.py",
    "example_07": "examples_legacy/07_analytical_solution_for_streamflow_recession/example_07.py",
    "example_08": "examples_legacy/08_exponential_distribution_of_residence_times/example_08.py",
    "example_09": "examples_legacy/09_transport_model_for_an_agricultural_catchment/example_09.py",
    "example_10": "examples_legacy/10_coupling_with_land_surface_model_pyhelp/example_10.py",
    "example_11": "examples_legacy/11_for run from scratch without plots/example_11.py",
}

CELL_METADATA = {"hydromodpy_generated_cell": "example_parameters"}


@dataclass(frozen=True)
class ParameterSpec:
    key: str
    section: str
    label: str
    meaning: str


@dataclass(frozen=True)
class ExpressionValue:
    text: str


@dataclass
class ParameterValue:
    value: Any
    source_name: str | None = None


PARAMETER_SPECS = [
    ParameterSpec(
        "source_script", "Overview", "source_script", "Python source mirrored by this notebook"
    ),
    ParameterSpec(
        "watershed_name", "Case Setup", "watershed_name", "Study site or case identifier"
    ),
    ParameterSpec("catch_def", "Case Setup", "catch_def", "Catchment extraction mode"),
    ParameterSpec(
        "from_dem",
        "Case Setup",
        "from_dem",
        "DEM input and working cell size when the case starts from a raster",
    ),
    ParameterSpec(
        "from_shp",
        "Case Setup",
        "from_shp",
        "Boundary shapefile and buffer when the case starts from a polygon",
    ),
    ParameterSpec(
        "from_xyv", "Case Setup", "from_xyv", "Outlet coordinates, snap distance, buffer, and CRS"
    ),
    ParameterSpec("model_name", "Core Parameters", "model_name", "Simulation or run identifier"),
    ParameterSpec("sim_state", "Core Parameters", "sim_state", "Flow regime used by the example"),
    ParameterSpec(
        "recharge", "Core Parameters", "recharge", "Recharge forcing passed to the flow model"
    ),
    ParameterSpec(
        "first_clim", "Core Parameters", "first_clim", "How the first climate step is initialized"
    ),
    ParameterSpec("nlay", "Core Parameters", "nlay", "Number of groundwater layers"),
    ParameterSpec(
        "lay_decay", "Core Parameters", "lay_decay", "Vertical layer-thickness decay factor"
    ),
    ParameterSpec(
        "thick", "Core Parameters", "thick", "Aquifer thickness when the bottom is not prescribed"
    ),
    ParameterSpec("bottom", "Core Parameters", "bottom", "Bottom elevation handling"),
    ParameterSpec("hk", "Core Parameters", "hk", "Hydraulic conductivity used for the default run"),
    ParameterSpec("sy", "Core Parameters", "sy", "Specific yield or drainable porosity"),
    ParameterSpec("ss", "Core Parameters", "ss", "Specific storage"),
    ParameterSpec("vka", "Core Parameters", "vka", "Horizontal to vertical conductivity ratio"),
    ParameterSpec(
        "sea_level",
        "Core Parameters",
        "sea_level",
        "Ocean boundary level when an oceanic boundary is active",
    ),
    ParameterSpec("bc_sides", "Core Parameters", "bc_sides", "Left and right boundary conditions"),
    ParameterSpec("track_dir", "Core Parameters", "track_dir", "Particle-tracking direction"),
    ParameterSpec(
        "hydraulic_conductivity_sweep",
        "Parameter Sweeps",
        "hydraulic_conductivity_sweep",
        "Conductivity values explored later in the notebook",
    ),
    ParameterSpec(
        "specific_yield_sweep",
        "Parameter Sweeps",
        "specific_yield_sweep",
        "Specific-yield or porosity values explored later in the notebook",
    ),
    ParameterSpec(
        "storage_sweep",
        "Parameter Sweeps",
        "storage_sweep",
        "Storage values explored later in the notebook",
    ),
]

SPEC_BY_KEY = {spec.key: spec for spec in PARAMETER_SPECS}

NAME_ALIASES = {
    "watershed_name": "watershed_name",
    "catch_def": "catch_def",
    "from_dem": "from_dem",
    "from_shp": "from_shp",
    "from_xyv": "from_xyv",
    "model_name": "model_name",
    "sim_state": "sim_state",
    "recharge": "recharge",
    "R": "recharge",
    "first_clim": "first_clim",
    "first_R": "first_clim",
    "nlay": "nlay",
    "lay_decay": "lay_decay",
    "thick": "thick",
    "thickness": "thick",
    "bottom": "bottom",
    "hk": "hk",
    "hyd_cond": "hk",
    "K": "hk",
    "the_K0": "hk",
    "sy": "sy",
    "Sy": "sy",
    "porosity": "sy",
    "the_sy0": "sy",
    "ss": "ss",
    "Ss": "ss",
    "the_ss0": "ss",
    "vka": "vka",
    "sea_level": "sea_level",
    "track_dir": "track_dir",
    "tracking_dir": "track_dir",
    "list_hyd_cond": "hydraulic_conductivity_sweep",
    "k_values": "hydraulic_conductivity_sweep",
    "list_porosity": "specific_yield_sweep",
    "list_sy": "specific_yield_sweep",
    "list_ss": "storage_sweep",
}

CALL_ALIASES = {
    "BV.settings.update_model_name": ("model_name", "model_name"),
    "BV.settings.update_simulation_state": ("sim_state", None),
    "BV.climatic.update_recharge": ("recharge", None),
    "BV.climatic.update_first_clim": ("first_clim", None),
    "BV.hydraulic.update_nlay": ("nlay", None),
    "BV.hydraulic.update_lay_decay": ("lay_decay", None),
    "BV.hydraulic.update_bottom": ("bottom", None),
    "BV.hydraulic.update_thick": ("thick", None),
    "BV.hydraulic.update_hk": ("hk", None),
    "BV.hydraulic.update_sy": ("sy", None),
    "BV.hydraulic.update_ss": ("ss", None),
    "BV.hydraulic.update_vka": ("vka", None),
}


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool, ExpressionValue)) or value is None


def _is_empty_value(key: str, value: Any) -> bool:
    if isinstance(value, ExpressionValue):
        text = value.text.strip()
        if key == "recharge":
            return False
        return text in {"None", "[]", "()"}
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in {"", "None"}
    if isinstance(value, (list, tuple)):
        if not value:
            return True
        if key == "bc_sides":
            return all(item in {None, "None"} for item in value)
    return False


def _unparse(node: ast.AST) -> str:
    return ast.unparse(node).strip()


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _to_numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _binary_op(left: Any, right: Any, operator: ast.operator) -> Any:
    left_num = _to_numeric(left)
    right_num = _to_numeric(right)
    if left_num is not None and right_num is not None:
        if isinstance(operator, ast.Add):
            return left_num + right_num
        if isinstance(operator, ast.Sub):
            return left_num - right_num
        if isinstance(operator, ast.Mult):
            return left_num * right_num
        if isinstance(operator, ast.Div):
            return left_num / right_num
        if isinstance(operator, ast.Pow):
            return left_num**right_num
    if isinstance(operator, ast.Add) and isinstance(left, str) and isinstance(right, str):
        return left + right
    if isinstance(left, list) and right_num is not None:
        return [
            _binary_op(item, right_num, operator) if _to_numeric(item) is not None else item
            for item in left
        ]
    if isinstance(right, list) and left_num is not None:
        return [
            _binary_op(left_num, item, operator) if _to_numeric(item) is not None else item
            for item in right
        ]
    raise ValueError("unsupported operation")


def _safe_eval(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id, ExpressionValue(node.id))
    if isinstance(node, ast.List):
        return [_safe_eval(item, env) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval(item, env) for item in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _safe_eval(key, env): _safe_eval(value, env)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    if isinstance(node, ast.UnaryOp):
        operand = _safe_eval(node.operand, env)
        number = _to_numeric(operand)
        if isinstance(node.op, ast.USub) and number is not None:
            return -number
        if isinstance(node.op, ast.UAdd) and number is not None:
            return number
        raise ValueError("unsupported unary op")
    if isinstance(node, ast.BinOp):
        left = _safe_eval(node.left, env)
        right = _safe_eval(node.right, env)
        return _binary_op(left, right, node.op)
    if isinstance(node, ast.Compare):
        left = _safe_eval(node.left, env)
        right = _safe_eval(node.comparators[0], env)
        if isinstance(node.ops[0], ast.Eq):
            return left == right
        if isinstance(node.ops[0], ast.NotEq):
            return left != right
        raise ValueError("unsupported comparison")
    if isinstance(node, ast.BoolOp):
        values = [_safe_eval(item, env) for item in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ValueError("unsupported boolean op")
    if isinstance(node, ast.Call):
        dotted = _dotted_name(node.func)
        args = [_safe_eval(arg, env) for arg in node.args]
        if dotted == "os.path.join" and all(isinstance(arg, str) for arg in args):
            return "/".join(part.strip("/\\") for part in args if part)
        if dotted in {"np.array", "pd.Series"} and len(args) == 1 and isinstance(args[0], list):
            return args[0]
        if dotted == "np.geomspace" and len(args) == 3:
            start = _to_numeric(args[0])
            stop = _to_numeric(args[1])
            count = _to_numeric(args[2])
            if start and stop and count:
                n = int(count)
                if n >= 2:
                    ratio = (stop / start) ** (1 / (n - 1))
                    return [start * (ratio**idx) for idx in range(n)]
        raise ValueError("unsupported call")
    raise ValueError("unsupported node")


def _evaluate(node: ast.AST, env: dict[str, Any]) -> Any:
    try:
        return _safe_eval(node, env)
    except Exception:
        return ExpressionValue(_unparse(node))


def _record_parameter(
    parameters: dict[str, ParameterValue], key: str, value: Any, source_name: str | None = None
) -> None:
    if key not in SPEC_BY_KEY or _is_empty_value(key, value):
        return
    existing = parameters.get(key)
    if existing is not None and isinstance(value, ExpressionValue):
        text = value.text.strip()
        if any(
            token in text
            for token in ("model_modflow", "list_folder[", "os.path.split(", "d[", ".mf.")
        ):
            return
        if text == (source_name or SPEC_BY_KEY[key].label):
            return
    parameters[key] = ParameterValue(value=value, source_name=source_name)


def _record_named_assignment(parameters: dict[str, ParameterValue], name: str, value: Any) -> None:
    key = NAME_ALIASES.get(name)
    if key is None:
        return
    _record_parameter(parameters, key, value, source_name=name)


def _record_call(
    parameters: dict[str, ParameterValue], dotted_name: str, call: ast.Call, env: dict[str, Any]
) -> None:
    if dotted_name == "BV.settings.update_bc_sides":
        if len(call.args) >= 2:
            left = _evaluate(call.args[0], env)
            right = _evaluate(call.args[1], env)
            _record_parameter(parameters, "bc_sides", (left, right))
        return
    if dotted_name == "BV.settings.update_input_particles":
        for keyword in call.keywords:
            if keyword.arg == "track_dir":
                _record_parameter(
                    parameters, "track_dir", _evaluate(keyword.value, env), source_name="track_dir"
                )
                return
        return
    mapped = CALL_ALIASES.get(dotted_name)
    if mapped is None or not call.args:
        return
    key, source_name = mapped
    _record_parameter(parameters, key, _evaluate(call.args[0], env), source_name=source_name)


def _assign_target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for item in target.elts:
            names.extend(_assign_target_names(item))
        return names
    return []


def _analyze_statements(
    statements: list[ast.stmt], env: dict[str, Any], parameters: dict[str, ParameterValue]
) -> None:
    for statement in statements:
        if isinstance(statement, ast.Assign):
            value = _evaluate(statement.value, env)
            for target in statement.targets:
                for name in _assign_target_names(target):
                    env[name] = value
                    _record_named_assignment(parameters, name, value)
            continue
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
        ):
            value = _evaluate(statement.value, env)
            env[statement.target.id] = value
            _record_named_assignment(parameters, statement.target.id, value)
            continue
        if isinstance(statement, ast.If):
            decision = _evaluate(statement.test, env)
            if isinstance(decision, bool):
                branch = statement.body if decision else statement.orelse
                _analyze_statements(branch, env, parameters)
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            dotted = _dotted_name(statement.value.func)
            if dotted:
                _record_call(parameters, dotted, statement.value, env)
            continue


def _analyze_source_text(source: str, source_label: str) -> dict[str, ParameterValue]:
    tree = ast.parse(source)
    parameters: dict[str, ParameterValue] = {}

    module_env: dict[str, Any] = {}
    _record_parameter(parameters, "source_script", source_label)
    _analyze_statements(tree.body, module_env, parameters)

    function_call: ast.Call | None = None
    function_node: ast.FunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run_hydromodpy":
            function_node = node
        call: ast.Call | None = None
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
        if call is not None and _dotted_name(call.func) == "run_hydromodpy":
            function_call = call
        if isinstance(node, ast.If) and _unparse(node.test) == "__name__ == '__main__'":
            for nested in node.body:
                nested_call: ast.Call | None = None
                if isinstance(nested, ast.Expr) and isinstance(nested.value, ast.Call):
                    nested_call = nested.value
                if isinstance(nested, ast.Assign) and isinstance(nested.value, ast.Call):
                    nested_call = nested.value
                if nested_call is not None and _dotted_name(nested_call.func) == "run_hydromodpy":
                    function_call = nested_call
    if function_node is not None:
        function_env = dict(module_env)
        positional = (
            function_node.args.args[-len(function_node.args.defaults) :]
            if function_node.args.defaults
            else []
        )
        for arg, default in zip(positional, function_node.args.defaults, strict=False):
            value = _evaluate(default, function_env)
            function_env[arg.arg] = value
            _record_named_assignment(parameters, arg.arg, value)
        if function_call is not None:
            for arg_node, arg_value in zip(
                function_node.args.args,
                function_call.args,
                strict=False,
            ):
                value = _evaluate(arg_value, module_env)
                function_env[arg_node.arg] = value
                _record_named_assignment(parameters, arg_node.arg, value)
            for keyword in function_call.keywords:
                if keyword.arg is None:
                    continue
                value = _evaluate(keyword.value, module_env)
                function_env[keyword.arg] = value
                _record_named_assignment(parameters, keyword.arg, value)
        _analyze_statements(function_node.body, function_env, parameters)
    return parameters


def _format_number(value: float) -> str:
    if math.isfinite(value):
        return f"{value:.6g}"
    return str(value)


def _format_sequence(values: list[Any] | tuple[Any, ...], key: str) -> str:
    items = list(values)
    if key == "bc_sides":
        return f"`[{_format_value(items[0], key)}, {_format_value(items[1], key)}]`"
    if key == "from_xyv" and len(items) <= 5:
        inner = ", ".join(_format_value(item, key) for item in items)
        return f"`[{inner}]`"
    if len(items) <= 5 and all(_is_scalar(item) for item in items):
        inner = ", ".join(_format_value(item, key) for item in items)
        return f"`[{inner}]`"
    if key == "recharge":
        preview = ", ".join(_format_value(item, key) for item in items[:3])
        tail = _format_value(items[-1], key)
        return f"`{len(items)}-step series: [{preview}, ..., {tail}]`"
    if all(_is_scalar(item) for item in items[:5]):
        preview = ", ".join(_format_value(item, key) for item in items[:3])
        tail = _format_value(items[-1], key)
        return f"`{len(items)} values: [{preview}, ..., {tail}]`"
    return f"`{len(items)} values`"


def _format_value(value: Any, key: str) -> str:
    if isinstance(value, ExpressionValue):
        text = value.text.strip()
        if key == "recharge":
            return "time-dependent series defined in the notebook"
        if len(text) > 72:
            return f"{text[:69]}..."
        return text
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return _format_number(float(value))
    if isinstance(value, (list, tuple)):
        return _format_sequence(value, key)
    return str(value)


def _render_section(title: str, rows: list[tuple[ParameterSpec, ParameterValue]]) -> list[str]:
    lines = [f"### {title}", "", "| Parameter | Meaning | Value |", "| --- | --- | --- |"]
    for spec, parameter in rows:
        rendered = _format_value(parameter.value, spec.key)
        if (
            not rendered.startswith("`")
            and rendered != "time-dependent series defined in the notebook"
        ):
            rendered = f"`{rendered}`"
        lines.append(f"| `{spec.label}` | {spec.meaning} | {rendered} |")
    lines.append("")
    return lines


def _build_markdown(notebook_name: str, parameters: dict[str, ParameterValue]) -> str:
    lines = [
        "## Example Parameters",
        "",
        "This notebook starts with the default or primary configuration used by the example script.",
        "Some later cells may sweep over several values or compare multiple runs; the tables below highlight the main case-specific choices.",
        "",
    ]
    for section in dict.fromkeys(spec.section for spec in PARAMETER_SPECS):
        rows = []
        for spec in PARAMETER_SPECS:
            if spec.section != section:
                continue
            parameter = parameters.get(spec.key)
            if parameter is None:
                continue
            rows.append((spec, parameter))
        if rows:
            lines.extend(_render_section(section, rows))
    lines.extend(
        [
            "### How To Use This Notebook",
            "",
            "- Read this block first, then scan the code cells that define the same variables.",
            "- If you change one of the values listed above, focus on the plots and exported files generated after the corresponding update call.",
            "- The authoritative source remains the Python script mirrored by this notebook.",
            "",
        ]
    )
    return "\n".join(lines)


def _normalize_notebook(data: dict[str, Any]) -> dict[str, Any]:
    _, normalized = normalize(nbf.from_dict(data))
    return normalized


def _read_notebook(notebook_path: Path) -> dict[str, Any]:
    data = json.loads(notebook_path.read_text(encoding="utf-8"))
    return _normalize_notebook(data)


def _write_notebook(notebook_path: Path, data: dict[str, Any]) -> None:
    normalized = _normalize_notebook(data)
    notebook_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def _upsert_generated_cell(notebook_path: Path, markdown: str) -> None:
    data = _read_notebook(notebook_path)
    cell = nbf.v4.new_markdown_cell(markdown)
    cell["source"] = [line + "\n" for line in markdown.rstrip().splitlines()]
    cell["metadata"] = dict(CELL_METADATA)
    cells = data.get("cells", [])
    insert_at = 1 if cells and cells[0].get("cell_type") == "markdown" else 0
    if (
        len(cells) > insert_at
        and cells[insert_at].get("metadata", {}).get("hydromodpy_generated_cell")
        == "example_parameters"
    ):
        existing_id = cells[insert_at].get("id")
        if existing_id:
            cell["id"] = existing_id
        cells[insert_at] = cell
    else:
        cells.insert(insert_at, cell)
    data["cells"] = cells
    _write_notebook(notebook_path, data)


def main() -> None:
    for notebook_stem, relative_source in NOTEBOOK_SOURCE_MAP.items():
        notebook_path = NOTEBOOK_DIR / f"{notebook_stem}.ipynb"
        notebook_data = _read_notebook(notebook_path)
        source_text = "\n\n".join(
            "".join(cell.get("source", []))
            for cell in notebook_data.get("cells", [])
            if cell.get("cell_type") == "code"
        )
        parameters = _analyze_source_text(source_text, relative_source)
        markdown = _build_markdown(notebook_stem, parameters)
        _upsert_generated_cell(notebook_path, markdown)
        print(f"updated {notebook_path.name}")


if __name__ == "__main__":
    main()
