"""
Sandboxed execution of candidate Python code.

Layers (defence in depth - this is a PROTOTYPE sandbox, see README):
  1. Static AST screen: only allow-listed imports, no eval/exec/open/getattr,
     no dunder or frame-introspection attribute access.
  2. Separate process, started with `python -I -S` from a throw-away directory
     and a scrubbed environment, never inside the server process.
  3. A trusted launcher applies OS limits BEFORE exec'ing the harness:
     CPU seconds, address space, file size, open files, process count, core dumps,
     and (when running as root) drops to the unprivileged `nobody` user.
     It also tries to detach into an empty network namespace.
  4. The harness runs the code with a reduced `__builtins__` and a guarded
     `__import__`; it only receives test inputs - expected answers never enter
     the sandbox process.
  5. Wall-clock timeout; the whole process group is killed on expiry.

For production use run this inside a container / gVisor / Firecracker VM (or
swap in Judge0); the interface below is the only thing the engine depends on.
"""
import ast
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
HARNESS = HERE / "sandbox_harness.py"

ALLOWED_MODULES = {
    "math", "itertools", "collections", "functools", "heapq", "bisect", "re",
    "string", "typing", "dataclasses", "statistics", "copy", "json", "decimal",
    "fractions", "random", "datetime", "enum", "abc", "array",
}
BANNED_NAMES = {
    "eval", "exec", "compile", "open", "input", "breakpoint", "getattr", "setattr",
    "delattr", "vars", "globals", "locals", "dir", "exit", "quit", "help",
    "__import__", "__builtins__", "__loader__", "__spec__", "memoryview",
}
ALLOWED_DUNDER_ATTRS = {
    "__init__", "__name__", "__doc__", "__len__", "__iter__", "__next__", "__eq__",
    "__lt__", "__le__", "__gt__", "__ge__", "__ne__", "__repr__", "__str__", "__hash__",
    "__contains__", "__getitem__", "__setitem__", "__delitem__", "__enter__", "__exit__",
    "__call__", "__add__", "__sub__", "__mul__", "__bool__",
}
BANNED_ATTRS = {
    "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "ag_frame", "ag_code",
    "f_back", "f_globals", "f_locals", "f_builtins", "f_code", "tb_frame", "tb_next",
    "co_code", "co_consts", "func_globals", "mro",
}

MAX_SOURCE_CHARS = 20000
CPU_SECONDS = 5
ADDRESS_SPACE = 384 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
WALL_TIMEOUT_S = 12
PER_TEST_S = 2.0

NOBODY = 65534

_LAUNCHER = r'''
import os, resource, sys
cpu, mem, fsize, drop, tmpdir = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] == "1", sys.argv[5]
resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
try:
    import ctypes
    ctypes.CDLL(None, use_errno=True).unshare(0x40000000)  # CLONE_NEWNET: no network (best effort)
except Exception:
    pass
os.chdir(tmpdir)
if drop:
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))  # no forks/threads once unprivileged
os.execv(sys.executable, [sys.executable, "-I", "-S", sys.argv[6]] + sys.argv[7:])
'''


class SandboxRejected(Exception):
    """Source failed the static screen; message is safe to show to the candidate."""


def screen_source(source: str) -> None:
    if not isinstance(source, str) or not source.strip():
        raise SandboxRejected("Your solution is empty.")
    if len(source) > MAX_SOURCE_CHARS:
        raise SandboxRejected("Solution is too long (limit %d characters)." % MAX_SOURCE_CHARS)
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise SandboxRejected("SyntaxError on line %s: %s" % (e.lineno, e.msg))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_MODULES:
                    raise SandboxRejected("Import of '%s' is not allowed in the assessment sandbox." % a.name)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in ALLOWED_MODULES:
                raise SandboxRejected("Import of '%s' is not allowed in the assessment sandbox." % (node.module or "."))
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise SandboxRejected("Use of '%s' is not allowed in the assessment sandbox." % node.id)
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRS or (
                node.attr.startswith("__") and node.attr.endswith("__") and node.attr not in ALLOWED_DUNDER_ATTRS
            ):
                raise SandboxRejected("Access to attribute '%s' is not allowed in the assessment sandbox." % node.attr)


_DROP_OK = None  # lazily probed: can the unprivileged user execute the interpreter?


def _spawn(args, workdir: Path, drop: bool, wall_timeout: float):
    harness = workdir / "harness.py"
    shutil.copyfile(HARNESS, harness)
    os.chmod(harness, 0o644)
    launcher = workdir / "launcher.py"
    launcher.write_text(_LAUNCHER)
    out_path, err_path = workdir / "out.txt", workdir / "err.txt"
    env = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "LANG": "C.UTF-8"}
    cmd = [sys.executable, "-I", "-S", str(launcher), str(CPU_SECONDS), str(ADDRESS_SPACE),
           str(MAX_FILE_BYTES), "1" if drop else "0", str(workdir), str(harness)] + args
    timed_out = False
    with open(out_path, "wb") as fo, open(err_path, "wb") as fe:
        p = subprocess.Popen(cmd, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL, env=env,
                             cwd=str(workdir), start_new_session=True, close_fds=True)
        try:
            p.wait(timeout=wall_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
    out = out_path.read_bytes()[:MAX_FILE_BYTES].decode("utf-8", "replace")
    return p.returncode, out, timed_out


def _run(spec: dict, per_test_s: float, wall_timeout: float):
    global _DROP_OK
    if _DROP_OK is None:
        _DROP_OK = _probe_privilege_drop()
    drop = os.geteuid() == 0 and _DROP_OK
    base = Path(tempfile.mkdtemp(prefix="stwin_sbx_"))
    try:
        os.chmod(base, 0o755)
        nonce = "@@" + secrets.token_hex(12) + "@@"
        spec_path = base / "spec.json"
        spec_path.write_text(json.dumps(spec))
        os.chmod(spec_path, 0o644)
        rc, out, timed_out = _spawn([str(spec_path), nonce, str(per_test_s)], base, drop, wall_timeout)
        lines = []
        for ln in out.splitlines():
            if ln.startswith(nonce):
                try:
                    lines.append(json.loads(ln[len(nonce):]))
                except ValueError:
                    pass
        return lines, timed_out, rc
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _probe_privilege_drop() -> bool:
    """Check once whether the unprivileged user can actually run the harness."""
    if os.geteuid() != 0:
        return False
    base = Path(tempfile.mkdtemp(prefix="stwin_probe_"))
    try:
        os.chmod(base, 0o755)
        spec = base / "spec.json"
        spec.write_text(json.dumps({"mode": "script", "source": "x = 1"}))
        os.chmod(spec, 0o644)
        rc, out, to = _spawn([str(spec), "@@probe@@", "2"], base, True, 10)
        return "@@probe@@" in out and not to
    except Exception:
        return False
    finally:
        shutil.rmtree(base, ignore_errors=True)


def describe() -> dict:
    global _DROP_OK
    if _DROP_OK is None:
        _DROP_OK = _probe_privilege_drop()
    root = os.geteuid() == 0
    return {
        "isolation": "separate process, rlimits (cpu/memory/fsize/files/nproc), reduced builtins, "
                     "import allow-list, static screening, wall-clock timeout",
        "privilege_drop_to_nobody": bool(root and _DROP_OK),
        "running_as_root": root,
        "warnings": ([] if (not root or _DROP_OK) else
                     ["Running as root but could not drop privileges; run the server as a non-root user."]),
        "production_note": "Prototype-grade sandbox. For production run it inside a container/gVisor/microVM or use Judge0.",
        "limits": {"cpu_seconds": CPU_SECONDS, "memory_mb": ADDRESS_SPACE // 1024 // 1024,
                   "per_test_seconds": PER_TEST_S, "wall_timeout_seconds": WALL_TIMEOUT_S},
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _matches(expected, got, approx=None) -> bool:
    if isinstance(expected, bool) or isinstance(got, bool):
        return isinstance(expected, bool) and isinstance(got, bool) and expected == got
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        if approx is not None:
            return abs(expected - got) <= approx
        return expected == got
    if isinstance(expected, dict) and isinstance(got, dict):
        return expected.keys() == got.keys() and all(_matches(expected[k], got[k], approx) for k in expected)
    if isinstance(expected, list) and isinstance(got, list):
        return len(expected) == len(got) and all(_matches(a, b, approx) for a, b in zip(expected, got))
    return expected == got


def run_function_tests(source: str, func: str, tests: list, *, per_test_s: float = PER_TEST_S,
                       wall_timeout: float = WALL_TIMEOUT_S) -> dict:
    """
    Execute `source` and evaluate function `func` against `tests`.

    Each test is one of:
      {"args": [...], "expected": X}                 plain call
      {"args": [...], "raises": "ValueError"}        must raise that exception type
      {"seq": [[args], [args]], "expected": [r, r]}  several calls sharing module state
      {"ctor": [...], "ops": [["method", arg...]], "expected": [r, ...]}  class protocol
    Optional "approx": float tolerance, "visible": bool (included in the report detail).

    Returns {"passed", "total", "score", "fatal", "timed_out", "results": [...]}.
    Hidden-test results never include inputs or expected values.
    """
    screen_source(source)  # raises SandboxRejected
    # Strip expected values / raise-expectations: the sandbox only needs inputs.
    inputs = []
    for t in tests:
        inputs.append({k: t[k] for k in ("args", "seq", "ctor", "ops") if k in t})
    spec = {"mode": "tests", "source": source, "func": func, "tests": inputs}
    lines, timed_out, rc = _run(spec, per_test_s, wall_timeout)

    fatal = next((l["fatal"] for l in lines if "fatal" in l), None)
    by_idx = {l["i"]: l for l in lines if "i" in l}
    results, passed = [], 0
    for i, t in enumerate(tests):
        r = by_idx.get(i)
        visible = bool(t.get("visible"))
        entry = {"index": i, "visible": visible}
        ok = False
        if r is None:
            entry["error"] = "time limit exceeded" if timed_out else (fatal or "no result")
        elif "error" in r:
            if "raises" in t and t["raises"] in r.get("exc", []):
                ok = True
            else:
                entry["error"] = r["error"]
        else:
            if "raises" in t:
                entry["error"] = "expected %s to be raised" % t["raises"]
            else:
                ok = _matches(t["expected"], r["got"], t.get("approx"))
                if visible:
                    entry["got"] = r["got"]
        entry["passed"] = ok
        if visible:
            entry["args"] = t.get("args", t.get("seq", t.get("ops")))
            entry["expected"] = t.get("expected", "raises " + t["raises"] if "raises" in t else None)
        passed += ok
        results.append(entry)
    total = len(tests)
    return {"passed": passed, "total": total, "score": (passed / total) if total else 0.0,
            "fatal": fatal, "timed_out": timed_out, "results": results}


def run_script(source: str, timeout: float = 8) -> dict:
    """Execute a snippet only to confirm it loads; used by bank self-tests."""
    screen_source(source)
    lines, timed_out, rc = _run({"mode": "script", "source": source}, PER_TEST_S, timeout)
    fatal = next((l["fatal"] for l in lines if "fatal" in l), None)
    return {"ok": any(l.get("done") for l in lines), "fatal": fatal, "timed_out": timed_out}
