"""
Runs INSIDE the sandbox child process (never imported by the server).

It executes candidate code in a restricted namespace and prints one JSON line
per test, prefixed with a per-run random nonce so candidate print() output can
never be mistaken for a result.

Design point: the harness is only ever given test INPUTS. Expected values stay
in the parent process, so candidate code cannot read or print them.
"""
import builtins
import copy
import json
import signal
import sys

# Bind the originals before any candidate code runs so patching the modules later has no effect.
_dumps = json.dumps
_deepcopy = copy.deepcopy
_sorted = sorted
_nonce_write = None

ALLOWED_MODULES = {
    "math", "itertools", "collections", "functools", "heapq", "bisect", "re",
    "string", "typing", "dataclasses", "statistics", "copy", "json", "decimal",
    "fractions", "random", "datetime", "enum", "abc", "array",
}

SAFE_BUILTIN_NAMES = """
abs all any ascii bin bool bytearray bytes callable chr complex dict divmod enumerate
filter float format frozenset hash hex id int isinstance issubclass iter len list map max
min next object oct ord pow print property range repr reversed round set slice sorted
staticmethod classmethod str sum super tuple type zip hasattr
True False None NotImplemented Ellipsis __build_class__
""".split()


def _build_safe_builtins(real_import):
    safe = {n: getattr(builtins, n) for n in SAFE_BUILTIN_NAMES if hasattr(builtins, n)}
    for n in dir(builtins):  # every exception class is fine to expose
        obj = getattr(builtins, n)
        if isinstance(obj, type) and issubclass(obj, BaseException):
            safe[n] = obj

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if level != 0 or root not in ALLOWED_MODULES:
            raise ImportError("import of '%s' is not allowed in the assessment sandbox" % name)
        return real_import(name, globals, locals, fromlist, level)

    safe["__import__"] = guarded_import
    safe["__name__"] = "solution"
    return safe


class _Timeout(BaseException):
    pass


def _on_alarm(signum, frame):
    raise _Timeout()


def canon(x, depth=0):
    """Reduce a result to JSON-native types (tuple->list, set->sorted list, ...)."""
    if depth > 40:
        raise ValueError("result nested too deeply")
    if x is None or isinstance(x, (bool, int, str)):
        return x
    if isinstance(x, float):
        if x != x or x in (float("inf"), float("-inf")):
            return {"__float__": repr(x)}
        return x
    if isinstance(x, (list, tuple)):
        return [canon(i, depth + 1) for i in x]
    if isinstance(x, (set, frozenset)):
        return _sorted((canon(i, depth + 1) for i in x), key=lambda v: _dumps(v, sort_keys=True))
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if not isinstance(k, str):
                k = repr(k)
            out[k] = canon(v, depth + 1)
        return out
    raise TypeError("unsupported result type: %s" % type(x).__name__)


def main():
    spec_path, nonce, per_test_s = sys.argv[1], sys.argv[2], float(sys.argv[3])
    with open(spec_path) as fh:
        spec = json.load(fh)
    real_out = sys.stdout

    class _Sink:
        def write(self, s):
            return len(s)

        def flush(self):
            pass

    def emit(obj):
        real_out.write(nonce + _dumps(obj) + "\n")
        real_out.flush()

    real_import = builtins.__import__
    g = {"__builtins__": _build_safe_builtins(real_import), "__name__": "solution"}
    sys.stdout = _Sink()
    sys.stderr = _Sink()
    signal.signal(signal.SIGALRM, _on_alarm)

    mode = spec["mode"]
    try:
        code = compile(spec["source"], "solution.py", "exec")
        signal.setitimer(signal.ITIMER_REAL, max(per_test_s, 1.0))
        exec(code, g)
        signal.setitimer(signal.ITIMER_REAL, 0)
    except _Timeout:
        emit({"fatal": "timeout while loading the submission"})
        return
    except BaseException as e:  # noqa: BLE001 - report any load failure
        signal.setitimer(signal.ITIMER_REAL, 0)
        emit({"fatal": "%s: %s" % (type(e).__name__, str(e)[:200])})
        return

    if mode == "script":
        emit({"done": True})
        return

    func_name = spec["func"]
    for i, t in enumerate(spec["tests"]):
        res = {"i": i}
        try:
            signal.setitimer(signal.ITIMER_REAL, per_test_s)
            target = g.get(func_name)
            if target is None:
                raise NameError("name '%s' is not defined" % func_name)
            if "ops" in t:  # stateful class test
                obj = target(*_deepcopy(t.get("ctor", [])))
                outs = []
                for op in t["ops"]:
                    outs.append(canon(getattr(obj, op[0])(*_deepcopy(op[1:]))))
                res["got"] = outs
            elif "seq" in t:  # several calls sharing module state
                outs = [target(*_deepcopy(a)) for a in t["seq"]]
                res["got"] = canon(outs)  # canonicalised AFTER all calls: exposes shared mutable state
            else:
                res["got"] = canon(target(*_deepcopy(t["args"])))
            signal.setitimer(signal.ITIMER_REAL, 0)
        except _Timeout:
            res["error"] = "timeout"
        except BaseException as e:  # noqa: BLE001
            signal.setitimer(signal.ITIMER_REAL, 0)
            res["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
            res["exc"] = [c.__name__ for c in type(e).__mro__]
        emit(res)
    emit({"done": True})


main()
