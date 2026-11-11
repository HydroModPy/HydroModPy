"""The package runs on Windows: the source holds no call that only POSIX has.

The gate reads the source of ``hydromodpy/`` and ``validation_cases/``, because
``fcntl``, ``pwd`` and ``grp`` enter ``sys.modules`` through the standard
library anyway. Seven rules, each with its table of allowed files and the
reason of each:

1. No import of ``fcntl``, ``msvcrt``, ``termios``, ``pwd`` or ``grp``;
   ``resource`` only inside ``try ... except ImportError``.
2. ``os.setsid``, ``os.killpg``, ``os.fork``, ``os.getuid``, ``os.geteuid``,
   ``os.getpgid``, ``signal.SIGKILL`` and ``signal.SIGHUP`` only under an
   ``if`` (or its ``else``) whose test reads ``os.name`` or ``sys.platform``.
3. ``socket.gethostname`` only in ``core/state/host.py``.
4. ``os.link`` and ``.hardlink_to`` only in ``core/io/filesystem.py``;
   ``os.symlink`` and ``.symlink_to`` nowhere.
5. A comparison of ``len(...)`` with an integer of the Windows path limits
   only in ``core/io/filesystem.py``.
6. No ``subprocess`` call runs a shell or a ``.sh`` script outside the SLURM
   launcher, and the run path does not load the SLURM launcher.
7. ``check_project_root`` refuses, under ``windows=True``, a root whose length
   plus ``PROJECT_TREE_DEPTH`` passes ``WINDOWS_PATH_LIMIT``.
"""

from __future__ import annotations

import ast
import functools
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.io.filesystem import (
    PROJECT_TREE_DEPTH,
    WINDOWS_PATH_LIMIT,
    check_project_root,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED_ROOTS = ("hydromodpy", "hydromodpy_server", "validation_cases")

Finding = tuple[int, str]
Detector = Callable[[ast.Module], list[Finding]]

POSIX_ONLY_MODULES = frozenset({"fcntl", "msvcrt", "termios", "pwd", "grp"})
GUARDED_MODULES = frozenset({"resource"})
POSIX_ONLY_CALLS = frozenset(
    {
        ("os", "setsid"),
        ("os", "killpg"),
        ("os", "fork"),
        ("os", "getuid"),
        ("os", "geteuid"),
        ("os", "getpgid"),
        ("signal", "SIGKILL"),
        ("signal", "SIGHUP"),
    }
)
WINDOWS_LENGTHS = frozenset({240, 247, 248, 255, 259, 260})
SHELLS = frozenset({"bash", "sh", "cmd", "powershell", "pwsh"})
SUBPROCESS_CALLS = frozenset({"run", "Popen", "call", "check_call", "check_output"})
RUN_PATH_MODULES = (
    "hydromodpy",
    "hydromodpy.project.api",
    "hydromodpy.project.runner",
    "hydromodpy.project.dispatch.workflow",
    "hydromodpy.cli.commands.run",
)
SLURM_MODULES = frozenset({"slurm", "sacct", "slurm_script"})

# Allowed files per rule, path relative to the repository root, with the reason.
ALLOWED_POSIX_IMPORTS: dict[str, str] = {}
ALLOWED_UNGUARDED_POSIX_CALLS: dict[str, str] = {}
ALLOWED_HOST_NAME = {
    "hydromodpy/core/state/host.py": "the one reader of the host name",
}
ALLOWED_HARD_LINKS = {
    "hydromodpy/core/io/filesystem.py": "link_or_copy falls back to a copy that never overwrites",
}
ALLOWED_SYMLINKS: dict[str, str] = {}
ALLOWED_LENGTH_LIMITS = {
    "hydromodpy/core/io/filesystem.py": "the one module that knows the Windows path limit",
}
ALLOWED_SHELLS = {
    "hydromodpy/project/launch/slurm.py": "the SLURM launcher submits its .sh scripts",
    "hydromodpy/project/launch/sacct.py": "the SLURM accounting reader of the launcher",
    "hydromodpy/project/launch/slurm_script.py": "writes the .sh scripts SLURM runs",
}


# --- Detectors, one per rule. Each returns (line, what) for a tree.


def _dotted(node: ast.AST) -> tuple[str, str] | None:
    """``(module, attribute)`` for ``module.attribute``, else None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id, node.attr
    return None


def _parents(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _ancestors(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> Iterator[tuple[ast.AST, ast.AST]]:
    """Each ancestor with the child of it on the way to ``node``."""
    while node in parents:
        parent = parents[node]
        yield parent, node
        node = parent


def _reads_the_platform(test: ast.AST) -> bool:
    return any(_dotted(node) in {("os", "name"), ("sys", "platform")} for node in ast.walk(test))


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    if caught is None:
        return False
    names = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(
        isinstance(name, ast.Name) and name.id in {"ImportError", "ModuleNotFoundError"}
        for name in names
    )


def _imported_modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module.split(".")[0]]
    return []


def posix_imports(tree: ast.Module) -> list[Finding]:
    """Rule 1: POSIX-only imports, and ``resource`` outside ``try ... except ImportError``."""
    parents = _parents(tree)
    found: list[Finding] = []
    for node in ast.walk(tree):
        for module in _imported_modules(node):
            if module in POSIX_ONLY_MODULES:
                found.append((node.lineno, f"import {module}"))
            elif module in GUARDED_MODULES and not any(
                isinstance(parent, ast.Try)
                and child in parent.body
                and any(_catches_import_error(handler) for handler in parent.handlers)
                for parent, child in _ancestors(node, parents)
            ):
                found.append((node.lineno, f"import {module} outside try/except ImportError"))
    return found


def unguarded_posix_calls(tree: ast.Module) -> list[Finding]:
    """Rule 2: POSIX-only names outside an ``if`` on ``os.name`` or ``sys.platform``."""
    parents = _parents(tree)
    found: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"os", "signal"}:
            for alias in node.names:
                if (node.module, alias.name) in POSIX_ONLY_CALLS:
                    found.append((node.lineno, f"from {node.module} import {alias.name}"))
            continue
        name = _dotted(node)
        if name not in POSIX_ONLY_CALLS:
            continue
        guarded = any(
            isinstance(parent, ast.If | ast.IfExp)
            and child is not parent.test
            and _reads_the_platform(parent.test)
            for parent, child in _ancestors(node, parents)
        )
        if not guarded:
            found.append((node.lineno, ".".join(name)))
    return found


def host_name_reads(tree: ast.Module) -> list[Finding]:
    """Rule 3: reads of ``socket.gethostname``."""
    found: list[Finding] = []
    for node in ast.walk(tree):
        if _dotted(node) == ("socket", "gethostname"):
            found.append((node.lineno, "socket.gethostname"))
        elif isinstance(node, ast.ImportFrom) and node.module == "socket":
            if any(alias.name == "gethostname" for alias in node.names):
                found.append((node.lineno, "from socket import gethostname"))
    return found


def _link_uses(tree: ast.Module, os_name: str, path_method: str) -> list[Finding]:
    found: list[Finding] = []
    for node in ast.walk(tree):
        if _dotted(node) == ("os", os_name):
            found.append((node.lineno, f"os.{os_name}"))
        elif isinstance(node, ast.Attribute) and node.attr == path_method:
            found.append((node.lineno, f".{path_method}"))
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            if any(alias.name == os_name for alias in node.names):
                found.append((node.lineno, f"from os import {os_name}"))
    return found


def hard_links(tree: ast.Module) -> list[Finding]:
    """Rule 4: ``os.link`` and ``.hardlink_to``."""
    return _link_uses(tree, "link", "hardlink_to")


def symlinks(tree: ast.Module) -> list[Finding]:
    """Rule 4: ``os.symlink`` and ``.symlink_to``."""
    return _link_uses(tree, "symlink", "symlink_to")


def _holds_len(node: ast.AST) -> bool:
    return any(
        isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "len"
        for call in ast.walk(node)
    )


def _is_windows_length(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant) and type(node.value) is int and node.value in WINDOWS_LENGTHS
    )


def length_limits(tree: ast.Module) -> list[Finding]:
    """Rule 5: a comparison of ``len(...)`` with a Windows path limit."""
    found: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if any(_holds_len(op) for op in operands) and any(
            _is_windows_length(op) for op in operands
        ):
            found.append((node.lineno, ast.unparse(node)))
    return found


def _subprocess_names(tree: ast.Module) -> set[str]:
    """Names bound by ``from subprocess import run`` and the like."""
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess"
        for alias in node.names
        if alias.name in SUBPROCESS_CALLS
    }


def _is_subprocess_call(call: ast.Call, bound: set[str]) -> bool:
    name = _dotted(call.func)
    if name is not None:
        return name[0] == "subprocess" and name[1] in SUBPROCESS_CALLS
    return isinstance(call.func, ast.Name) and call.func.id in bound


def _program_of(arg: ast.AST) -> str | None:
    """The program a command names: first item of a list, first word of a string."""
    if isinstance(arg, ast.List | ast.Tuple) and arg.elts:
        arg = arg.elts[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.strip():
        program = arg.value.split()[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        return program.removesuffix(".exe")
    return None


def shell_calls(tree: ast.Module) -> list[Finding]:
    """Rule 6: ``shell=True``, a shell program, or a ``.sh`` literal in a subprocess call."""
    bound = _subprocess_names(tree)
    found: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_subprocess_call(node, bound):
            continue
        for keyword in node.keywords:
            if keyword.arg == "shell" and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value is False
            ):
                found.append((node.lineno, "shell=True"))
        if node.args and _program_of(node.args[0]) in SHELLS:
            found.append((node.lineno, f"runs {_program_of(node.args[0])}"))
        for literal in ast.walk(node):
            if (
                isinstance(literal, ast.Constant)
                and isinstance(literal.value, str)
                and literal.value.endswith(".sh")
            ):
                found.append((node.lineno, f"runs {literal.value}"))
    return found


# --- The source, parsed once.


@functools.cache
def _sources() -> tuple[tuple[str, ast.Module], ...]:
    parsed = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            parsed.append((rel, ast.parse(path.read_text(encoding="utf-8"), filename=rel)))
    return tuple(parsed)


def _violations(detector: Detector, allowed: dict[str, str]) -> list[str]:
    return [
        f"{rel}:{line}: {what}"
        for rel, tree in _sources()
        if rel not in allowed
        for line, what in detector(tree)
    ]


RULES = [
    pytest.param(posix_imports, ALLOWED_POSIX_IMPORTS, id="1-posix-imports"),
    pytest.param(unguarded_posix_calls, ALLOWED_UNGUARDED_POSIX_CALLS, id="2-posix-calls"),
    pytest.param(host_name_reads, ALLOWED_HOST_NAME, id="3-host-name"),
    pytest.param(hard_links, ALLOWED_HARD_LINKS, id="4-hard-links"),
    pytest.param(symlinks, ALLOWED_SYMLINKS, id="4-symlinks"),
    pytest.param(length_limits, ALLOWED_LENGTH_LIMITS, id="5-length-limits"),
    pytest.param(shell_calls, ALLOWED_SHELLS, id="6-shells"),
]


def test_the_scan_reads_the_package() -> None:
    scanned = {rel for rel, _ in _sources()}
    assert "hydromodpy/core/io/filesystem.py" in scanned
    assert "hydromodpy/core/state/host.py" in scanned
    assert any(rel.startswith("validation_cases/") for rel in scanned)


@pytest.mark.parametrize(("detector", "allowed"), RULES)
def test_the_source_keeps_the_rule(detector: Detector, allowed: dict[str, str]) -> None:
    violations = _violations(detector, allowed)
    assert violations == [], "\n".join(violations)


@pytest.mark.parametrize(("detector", "allowed"), RULES)
def test_each_allowed_file_exists(detector: Detector, allowed: dict[str, str]) -> None:
    for rel, reason in allowed.items():
        assert (REPO_ROOT / rel).is_file(), f"{rel} is allowed ({reason}) but is gone"


# --- Each detector, on code it must flag and code it must let pass.

DETECTOR_CASES = [
    (posix_imports, "import fcntl", 1),
    (posix_imports, "from pwd import getpwuid", 1),
    (posix_imports, "import grp, termios, msvcrt", 3),
    (posix_imports, "import resource", 1),
    (posix_imports, "try:\n    import resource\nexcept ImportError:\n    resource = None", 0),
    (posix_imports, "try:\n    import resource\nexcept OSError:\n    resource = None", 1),
    (posix_imports, "from importlib import resources", 0),
    (unguarded_posix_calls, "import os\nos.setsid()", 1),
    (unguarded_posix_calls, "import os, signal\nos.killpg(1, signal.SIGKILL)", 2),
    (unguarded_posix_calls, "from os import fork", 1),
    (unguarded_posix_calls, "import os\nif os.name == 'nt':\n    pass\nelse:\n    os.setsid()", 0),
    (unguarded_posix_calls, "import os, sys\nif sys.platform != 'win32':\n    os.getuid()", 0),
    (unguarded_posix_calls, "import os\nif os.getuid():\n    pass", 1),
    (unguarded_posix_calls, "import os\nx = os.geteuid() if os.name != 'nt' else 0", 0),
    (host_name_reads, "import socket\nsocket.gethostname()", 1),
    (host_name_reads, "from socket import gethostname", 1),
    (host_name_reads, "import socket\nsocket.getfqdn()", 0),
    (hard_links, "import os\nos.link('a', 'b')", 1),
    (hard_links, "from pathlib import Path\nPath('b').hardlink_to('a')", 1),
    (hard_links, "import os\nos.unlink('a')", 0),
    (symlinks, "import os\nos.symlink('a', 'b')", 1),
    (symlinks, "from pathlib import Path\nPath('b').symlink_to('a')", 1),
    (symlinks, "import os\nos.readlink('a')", 0),
    (length_limits, "x = len(p) > 259", 1),
    (length_limits, "x = 240 <= len(str(p))", 1),
    (length_limits, "x = len(p) + 1 > 260", 1),
    (length_limits, "x = len(p) > LIMIT", 0),
    (length_limits, "x = code == 259", 0),
    (length_limits, "x = len(p) > 100", 0),
    (shell_calls, "import subprocess\nsubprocess.run('ls', shell=True)", 1),
    (shell_calls, "import subprocess\nsubprocess.run(['bash', '-c', 'ls'])", 1),
    (shell_calls, "import subprocess\nsubprocess.Popen(['/bin/sh', 'x'])", 1),
    (shell_calls, "import subprocess\nsubprocess.run(['powershell.exe', '-c', 'x'])", 1),
    (shell_calls, "import subprocess\nsubprocess.check_call(['cmd', '/c', 'dir'])", 1),
    (shell_calls, "from subprocess import run\nrun(['sbatch', 'array.sh'])", 1),
    (shell_calls, "import subprocess\nsubprocess.run(['taskkill', '/F', '/T'], check=False)", 0),
    (shell_calls, "import subprocess\nsubprocess.run(['mf6'], shell=False)", 0),
]


@pytest.mark.parametrize(
    ("detector", "source", "count"),
    DETECTOR_CASES,
    ids=[f"{d.__name__}-{i}" for i, (d, _, _) in enumerate(DETECTOR_CASES)],
)
def test_each_detector_flags_what_it_must(detector: Detector, source: str, count: int) -> None:
    assert len(detector(ast.parse(source))) == count


# --- Rule 6, second half: the run path does not load the SLURM launcher.


@pytest.mark.allow_subprocess
def test_the_run_path_does_not_load_the_slurm_launcher() -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "import importlib\n"
        f"for name in {RUN_PATH_MODULES!r}:\n"
        "    importlib.import_module(name)\n"
        "loaded = sorted(\n"
        "    name for name in sys.modules\n"
        "    if name.startswith('hydromodpy') and name.rsplit('.', 1)[-1] in "
        f"{sorted(SLURM_MODULES)!r}\n"
        ")\n"
        "print('\\n'.join(loaded))\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.split() == []


# --- Rule 7: the bound of a project root, played on Linux.


@pytest.mark.parametrize(
    ("length", "refused"),
    [
        (WINDOWS_PATH_LIMIT - PROJECT_TREE_DEPTH, False),
        (WINDOWS_PATH_LIMIT - PROJECT_TREE_DEPTH + 1, True),
        (WINDOWS_PATH_LIMIT, True),
    ],
    ids=["at-the-limit", "one-past", "the-whole-limit"],
)
def test_a_project_root_past_the_windows_budget_is_refused(length: int, refused: bool) -> None:
    root = "/" + "r" * (length - 1) if sys.platform != "win32" else "C:\\" + "r" * (length - 3)
    if refused:
        with pytest.raises(ConfigError, match=f"is {length} characters long"):
            check_project_root(root, windows=True)
    else:
        check_project_root(root, windows=True)
