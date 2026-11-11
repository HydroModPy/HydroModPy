"""No verb reads the process environment for its bounds.

A call declares what it may reach -- the hosts of a download, the roots a
named path sits under, its byte ceiling and delay, the credentials file --
and declares it through an ``Environment`` argument, built by the command
line or by the server. Reading ``os.environ`` or ``os.getenv`` for any of
that, anywhere in ``hydromodpy/``, would put the setting back where a caller
cannot see it: a server keeps one process per call and gives it an object.

Two tables keep the promise. ``environment_reads.yaml`` carries one row per
site the scan finds (and one per network client the arbiter counted), each
with its class; a site without a row and a row without a site both fail, so
the file only shrinks. This test also refuses a row in the files that carry
the bounds themselves, a variable named after a credential or a ceiling, an
environment write outside the classes that do it once per process, and a
network client the table does not name.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

import yaml

HERE = Path(__file__).parent
REPO = HERE.parents[2]
PACKAGE = REPO / "hydromodpy"
TABLE = yaml.safe_load((HERE / "environment_reads.yaml").read_text(encoding="utf-8"))

CLASSES = ("machine", "process", "cli", "diagnostic", "child", "transitional")

# The files that carry the types, the credentials reader, the port, and the one
# The files that carry the types, the credentials reader, the port, and the
# two client modules the fetch client of lot 4.3 replaces; none of the files
# below may read the environment.
NO_ENVIRONMENT_FILES = (
    "hydromodpy/core/io/http_client.py",
    "hydromodpy/core/io/pinned_download.py",
    "hydromodpy/core/runtime/bounds.py",
    "hydromodpy/project/environment.py",
    "hydromodpy/project/credentials.py",
    "hydromodpy/data/source/port.py",
)

# A host list, a credential or a ceiling never arrive through a variable.
FORBIDDEN_NAME = re.compile("CREDENTIAL|PASSWORD|TOKEN|NETRC|ALLOW|MAX_DOWNLOAD")

# The callables that receive the Environment by keyword, with their file.
GREEN_KWARG_FILES = (
    ("hydromodpy/_api.py", ("run", "calibrate", "spinup", "export")),
    ("hydromodpy/project/facade.py", ("Project.__init__", "Project.launch")),
)


def _scan_file(path: Path, relative: str) -> list[tuple[str, str]]:
    """Return the (kind, variable) pairs one file touches ``os.environ`` with.

    The same walk the table was generated from: a subscript or attribute read
    is a read, a subscript store or del and the putenv/pop calls are writes,
    and the whole ``os.environ`` object passed somewhere is a pass.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    constants: dict[str, str] = {}
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            value = node.value.value
            if isinstance(value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = value
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def is_module_environ(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "environ"
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        )

    def name_of(node: ast.AST) -> str:
        if isinstance(node, ast.Constant):
            return str(node.value)
        if isinstance(node, ast.Name):
            return constants.get(node.id, f"<{node.id}>")
        if isinstance(node, ast.Attribute):
            return f"<{ast.unparse(node)}>"
        return "<expr>"

    sites: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        kind = variable = None
        if is_module_environ(node):
            parent = parents.get(node)
            if isinstance(parent, ast.Attribute) and parent.attr in ("get", "pop", "setdefault"):
                call = parents.get(parent)
                if isinstance(call, ast.Call) and call.args:
                    variable = name_of(call.args[0])
                    kind = "read" if parent.attr == "get" else "write"
            elif isinstance(parent, ast.Subscript):
                variable = name_of(parent.slice)
                kind = "read" if isinstance(parent.ctx, ast.Load) else "write"
            elif isinstance(parent, ast.Compare):
                kind, variable = "read", name_of(parent.left)
            else:
                kind, variable = "pass", "<whole>"
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("getenv", "putenv")
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            kind = "read" if node.func.attr == "getenv" else "write"
            variable = name_of(node.args[0]) if node.args else "<expr>"
        if kind and variable:
            sites.append((kind, variable))
    return sites


def _scan_package() -> dict[str, list[tuple[str, str]]]:
    found: dict[str, list[tuple[str, str]]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        found[path.relative_to(REPO).as_posix()] = _scan_file(
            path, path.relative_to(REPO).as_posix()
        )
    return found


def _table_sites() -> list[tuple[str, str]]:
    return [(row["file"], row["kind"], row["variable"]) for row in TABLE["rows"]]


def test_every_site_has_its_row_and_every_row_its_site() -> None:
    found = [
        (file, kind, variable)
        for file, sites in _scan_package().items()
        for kind, variable in sites
    ]
    carried = _table_sites()
    unexpected = sorted(Counter(found) - Counter(carried))
    stale = sorted(Counter(carried) - Counter(found))
    assert not unexpected and not stale, (
        "The environment rows of hydromodpy/ and of environment_reads.yaml "
        "disagree. Sites without a row: "
        f"{unexpected}. Rows without a site: {stale}. A row leaves only with "
        "the code that read it, and a new read needs its row, its class and its why."
    )


def test_the_files_that_carry_the_bounds_read_no_environment() -> None:
    found = _scan_package()
    offenders = {
        file: sites for file, sites in found.items() if file in NO_ENVIRONMENT_FILES and sites
    }
    assert not offenders, (
        f"{offenders}: bounds, credentials and the fetch port read no "
        "environment variable; a caller builds the Bounds or the Environment "
        "and passes it."
    )


def test_no_variable_named_like_a_secret_or_a_bound_is_read() -> None:
    counted = Counter(
        row["variable"] for row in TABLE["rows"] if FORBIDDEN_NAME.search(row["variable"])
    )
    assert not counted, (
        f"{dict(counted)}: a host list, a credential or a ceiling never arrives "
        "through an environment variable."
    )


def test_rows_carry_a_known_class_and_transitional_ones_name_the_lot() -> None:
    for row in TABLE["rows"]:
        assert row["class"] in CLASSES, f"{row} is not in {CLASSES}"
        if row["class"] == "transitional":
            assert row.get("lifted_by"), f"a transitional row without lifted_by: {row}"
        else:
            assert not row.get("lifted_by"), f"{row['file']} is not transitional: {row}"
        assert len(row["why"].split()) >= 4, f"the why of {row} is too short"


def test_environment_writes_happen_only_once_per_process() -> None:
    writers = Counter(row["class"] for row in TABLE["rows"] if row["kind"] == "write")
    wrong = {cls for cls in writers if cls not in ("process", "transitional")}
    assert not wrong, f"{wrong}: an environment write happens once, at import or at a start"


def _environment_parameter(function: ast.FunctionDef) -> ast.arg | None:
    """Return the ``environment`` argument of ``function``, keyword-only expected."""
    for argument in function.args.kwonlyargs:
        if argument.arg == "environment":
            return argument
    for argument in function.args.args:
        if argument.arg == "environment":
            return argument
    return None


def test_the_verbs_and_the_project_receive_the_environment_by_keyword() -> None:
    missing: list[str] = []
    for relative, names in GREEN_KWARG_FILES:
        tree = ast.parse((REPO / relative).read_text(encoding="utf-8"), filename=relative)
        definitions: dict[str, ast.FunctionDef] = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                definitions[node.name] = node
            elif isinstance(node, ast.ClassDef) and node.name == "Project":
                for child in node.body:
                    if isinstance(child, ast.FunctionDef):
                        definitions[f"Project.{child.name}"] = child
        for name in names:
            function = definitions.get(name)
            if function is None:
                missing.append(f"{relative}:{name} has no function to read")
                continue
            parameter = _environment_parameter(function)
            if parameter is None:
                missing.append(f"{relative}:{name} takes no environment argument")
                continue
            annotation = ast.unparse(parameter.annotation).replace(" ", "")
            default = _default_of_kwonly(function, parameter)
            if parameter not in function.args.kwonlyargs or default != "None":
                missing.append(f"{relative}:{name}.environment is not keyword-only None")
            if annotation != "Environment|None":
                missing.append(f"{relative}:{name}.environment is annotated {annotation!r}")
    assert not missing, (
        "run, calibrate, spinup, export, Project.__init__ and Project.launch "
        f"take environment=Environment | None = None, keyword-only: {missing}"
    )


def _default_of_kwonly(function: ast.FunctionDef, parameter: ast.arg) -> str | None:
    """Return the unparsed default of a keyword-only argument."""
    for argument, default in zip(function.args.kwonlyargs, function.args.kw_defaults):
        if argument is parameter and default is not None:
            return ast.unparse(default)
    return None


def _network_clients() -> Counter[tuple[str, str]]:
    """Return every network client site, counted per (file, kind).

    ``requests.Session()``, the two ``urllib.request`` calls, ``ftplib.FTP``,
    ``ftplib.FTP_TLS`` and ``paramiko.Transport`` are the forms a client site
    can take. Every one is counted: a second client in a file that already
    carries a row fails the gate, not just a client in a new file. The fetch
    client of core/io/fetch.py trusts no environment.
    """
    found: Counter[tuple[str, str]] = Counter()
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            attribute, value = node.func.attr, node.func.value
            client = path.relative_to(REPO).as_posix()
            if attribute == "Session" and _object_name(value) == "requests":
                found[(client, "requests-session")] += 1
            elif attribute in ("urlopen", "urlretrieve") and _is_urllib_request(value):
                found[(client, "urllib")] += 1
            elif attribute == "FTP" and _object_name(value) == "ftplib":
                found[(client, "ftplib-ftp")] += 1
            elif attribute == "FTP_TLS" and _object_name(value) == "ftplib":
                found[(client, "ftplib-ftps")] += 1
            elif attribute == "Transport" and _object_name(value) == "paramiko":
                found[(client, "paramiko-sftp")] += 1
    return found


def _object_name(value: ast.AST) -> str:
    return value.id if isinstance(value, ast.Name) else ""


def _is_urllib_request(value: ast.AST) -> bool:
    return (
        isinstance(value, ast.Attribute)
        and value.attr == "request"
        and isinstance(value.value, ast.Name)
        and value.value.id == "urllib"
    )


def test_the_network_clients_are_the_ones_declared() -> None:
    found = _network_clients()
    carried = Counter((row["file"], row["client"]) for row in TABLE["network"])
    unexpected = sorted(found - carried)
    stale = sorted(carried - found)
    assert not unexpected and not stale, (
        "The network clients and environment_reads.yaml disagree, counted per "
        f"site: clients without a row {unexpected}, rows without a client "
        f"{stale}. Every download goes through core/io/fetch.py."
    )
    assert list(carried) == [
        ("hydromodpy/core/io/fetch.py", "requests-session"),
        ("hydromodpy/project/deliver.py", "ftplib-ftp"),
        ("hydromodpy/project/deliver.py", "ftplib-ftps"),
        ("hydromodpy/project/deliver.py", "paramiko-sftp"),
    ]
    source = (REPO / "hydromodpy" / "core" / "io" / "fetch.py").read_text(encoding="utf-8")
    assert "trust_env = False" in source, "the fetch client must not read the environment"
