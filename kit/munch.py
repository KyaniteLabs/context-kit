"""Munch reads + the mtime-validated read cache.

Two attacks on the same problem — your agent re-reading files it has already
seen, and reading whole files when it needs one symbol:

1. read_symbol  — symbol-level file access via stdlib `ast` (Python files).
   On our exploration suite this replaced a 13,917 B whole-file read with a
   276 B symbol read (-98% tool bytes; prompt 53.5 KB -> 4.9 KB, -91%).
   VALIDITY: CLEAN/structural (bytes are deterministic file-vs-stub, n=1).
   Wall time 48.6 s -> 22.6 s on the exploration task is DIRECTIONAL only
   (n=1, measured in a harness window later found to distort tool calls).

2. ResultCache — a repeat read of an UNCHANGED file (mtime_ns + size match)
   returns the cached bytes with zero re-execution.

Cache laws (keep all three or drop the cache):
  - READ-ONLY TOOLS ONLY. Side-effecting tools (shell, write, edit) are never
    cached; their safety lives in an effect ledger instead
    (docs/PATTERNS.md, "Idempotent effect ledger").
  - THE FULL CACHED RESULT FLOWS BACK. The model may genuinely need the
    content. Context savings come from projection-time dedup of identical
    bytes (kit/diet.py), not from truncating here.
  - VALIDATE BEFORE EVERY HIT. Re-stat the file; mtime_ns or size mismatch
    invalidates. Stamp mtime AFTER execution (make-style) so a file modified
    during the read is caught next time.

Zero dependencies. Stdlib only.
"""

import ast
import os
import time
import threading


# ------------------------------------------------------------- munch reads
def read_symbol(path, name, want_body=False):
    """Read one function/class from a .py file by name.

    Returns "kind name  # path:line-line" + first docstring line, plus the
    full source when want_body=True. A miss lists candidate symbol names so
    the model can retry cheaply instead of falling back to read_file.
    Python files only — other types get an explicit error.
    """
    if not path.endswith(".py"):
        return ("ERROR: read_symbol supports .py only "
                "(use read_file for other types)")
    tree = ast.parse(open(path, errors="replace").read())
    for node in ast.walk(tree):
        hit = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef)) and node.name == name
        if not hit:
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else "def"
        doc = (ast.get_docstring(node) or "").split("\n")[0][:160]
        span = f"{path}:{node.lineno}-{node.end_lineno}"
        sig = f"{kind} {name}  # {span}\n  {doc}" if doc else f"{kind} {name}  # {span}"
        if want_body:
            src = open(path, errors="replace").read().splitlines()
            body = "\n".join(src[node.lineno - 1:node.end_lineno])[:24000]
            return sig + "\n" + body
        return sig + "\n  (pass body=true for the full source)"
    # Not found by exact name: list candidates for a cheap retry.
    cands = [n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef))]
    return (f"ERROR: symbol '{name}' not in {path}. "
            f"Candidates: {', '.join(cands[:40])}")


# ------------------------------------------------------ mtime read cache
class ResultCache:
    """Read-only tool result cache, validated by (mtime_ns, size).

    Keys are arbitrary strings you derive from the call (tool + path + any
    args that shape the result). File-backed lookups re-stat on every hit;
    keys registered via `ttl` (no file to stat — graphs, indexes, searches)
    expire by age instead. LRU-evicts past `cap`.

    Set `stat_hook` to a (key, hit, age) sink for cache telemetry — it must
    never raise into a tool call (wrapped here, but keep sinks dull).
    """

    def __init__(self, cap=50, ttl_s=300):
        self.cap = cap
        self.ttl_s = ttl_s
        self._ent = {}          # key -> {result, mtime_ns, size, born, at}
        self._lock = threading.Lock()
        self.stat_hook = None

    def lookup(self, key, path=None):
        """Validated lookup. path=None means "TTL-validated key" (no file to
        stat). Returns the cached result on a hit, None on any miss."""
        with self._lock:
            ent = self._ent.get(key)
            if ent is None:
                return None
            if path is None:
                if time.time() - ent["born"] > self.ttl_s:
                    self._ent.pop(key, None)
                    return None
            else:
                try:
                    st = os.stat(path)
                except OSError:
                    self._ent.pop(key, None)   # missing file: bypass
                    return None
                if (st.st_mtime_ns, st.st_size) != (ent["mtime_ns"], ent["size"]):
                    self._ent.pop(key, None)   # changed on disk: invalidate
                    return None
            ent["at"] = time.time()            # LRU touch
            result = ent["result"]
        self._notify(key, True)
        return result

    def store(self, key, result, path=None):
        """Cache a successful read. mtime is stamped AFTER execution
        (make-style) so a file modified mid-read invalidates next time."""
        ent = {"result": result, "born": time.time(), "at": time.time()}
        if path is not None:
            st = os.stat(path)
            ent["mtime_ns"], ent["size"] = st.st_mtime_ns, st.st_size
        with self._lock:
            self._ent[key] = ent
            while len(self._ent) > self.cap:   # LRU-evict oldest last-access
                oldest = min(self._ent, key=lambda k: self._ent[k]["at"])
                del self._ent[oldest]
        self._notify(key, False)

    def _notify(self, key, hit):
        hook = self.stat_hook
        if hook:
            try:
                hook(key, hit)
            except Exception:
                pass            # telemetry must never break a tool call


# ------------------------------------------------------------ integration
def cached_read(cache, path, execute):
    """Reference wiring for a read-only tool dispatch.

    `execute(path)` performs the real read on a miss. The caller's tool
    contract is unchanged: same args in, same bytes out — the model cannot
    observe the cache except by the clock. Remember the cache laws in the
    module docstring: read-only tools only, full bytes back, never wrap a
    side-effecting tool.
    """
    key = f"read|{path}"
    result = cache.lookup(key, path=path)
    if result is not None:
        return result
    result = execute(path)
    if not result.startswith("ERROR"):
        try:
            cache.store(key, result, path=path)
        except Exception:
            pass                # the cache must never break a tool call
    return result
