"""Context diet: projection-time dedup/compaction + progressive disclosure.

The model-visible context is a PROJECTION of an append-only event log; the
log keeps everything forever, the view slims. Nothing here rewrites history —
every function takes event dicts and returns copies, originals untouched.

Two measured effects on our rig (see README.md for labels):
  - identical repeated tool outputs collapse to a stub: 3x 5 KB repeats of
    one command project to ~5.1 KB instead of 15 KB = -66% on that class of
    repetition (VALIDITY: ARITHMETIC — deterministic bytes, suite-proven).
  - combined with munch reads, prompt bytes on the exploration task fell
    53.5 KB -> 4.9 KB = -91% (VALIDITY: CLEAN/structural, n=1).

Why bother: at ~390 tok/s prefill, every 10k tokens not re-sent saves ~26 s
of time-to-first-token (ARITHMETIC). Late-turn prefill is where local-agent
pain lives.

Zero dependencies. Stdlib only. Events are plain dicts; the only convention
is {"kind": "tool_result", "content": str} plus your own fields, which pass
through untouched.
"""

import hashlib
import os
import threading

DEFAULT_SPILL_DIR = os.path.expanduser("~/.cache/context-kit/spill")


# ------------------------------------------------- pass 1: budget elision
def elide_to_budget(events, budget_chars=300000):
    """Fit the projection under a char budget. Oldest tool_result bodies are
    elided first (view-only; a 200-char preview survives so the model knows
    what it saw); if that is not enough, whole oldest events drop. Never
    touches the log — returns a new list."""
    keep = list(events)
    total = sum(len(e.get("content", "")) for e in keep)
    i = 0
    while total > budget_chars and i < len(keep):
        if keep[i].get("kind") == "tool_result":
            body = keep[i].get("content", "")
            total -= len(body)
            keep[i] = dict(keep[i], content="(elided)", _elided=body[:200])
        i += 1
    while total > budget_chars and len(keep) > 8:
        total -= len(keep[0].get("content", ""))
        keep.pop(0)
    return keep


# --------------------------------------------- pass 2: dedup + compaction
def dedup_identical(events, min_body=200):
    """Identical repeated tool outputs collapse to a stub — agents re-run the
    same command and re-read the same file constantly; the model only needs
    to know it saw this exact output before. Bodies under min_body are left
    alone (a stub is not cheaper than the body). Copy-on-write; returns a
    new list."""
    keep = list(events)
    seen = {}
    for idx, e in enumerate(keep):
        if e.get("kind") != "tool_result":
            continue
        body = e.get("content", "")
        if len(body) < min_body:
            continue
        h = hash(body)
        if h in seen:
            keep[idx] = dict(e, content=(
                f"(unchanged output — identical to the earlier result at "
                f"event {seen[h] + 1})"))
        else:
            seen[h] = idx
    return keep


def compact_old(events, keep_recent=40, long_session=300, min_body=400):
    """Long-session compaction: once the log exceeds `long_session` events,
    old tool bodies (everything except the newest `keep_recent`) stub down
    regardless of char budget. Late-turn time-to-first-token is where
    prefill pain hurts most; the recent window the model is actively working
    in stays full-fidelity."""
    if len(events) <= long_session:
        return list(events)
    keep = list(events)
    for idx in range(len(keep) - keep_recent):
        e = keep[idx]
        if e.get("kind") != "tool_result":
            continue
        body = e.get("content", "")
        if len(body) > min_body:
            keep[idx] = dict(e, content=(
                f"(old result, {len(body)}B — elided by compaction)"))
    return keep


def project(events, budget_chars=300000, **kw):
    """The full diet, in order: budget elision -> dedup -> compaction.
    Compose the passes differently if your workload says so; the invariant
    is that the INPUT list is never mutated."""
    return compact_old(
        dedup_identical(elide_to_budget(events, budget_chars), **kw))


# --------------------------------------- progressive disclosure (spill)
class SpillStats:
    """Read-back guard for the spill pattern. A spill that the model keeps
    reading back is negative-sum: you paid to truncate, then paid again to
    re-fetch. If readbacks exceed ~15% of spills, raise the disclose limit
    or stop spilling that output class."""

    def __init__(self):
        self.spilled = 0
        self.readbacks = 0
        self._lock = threading.Lock()

    def note_spill(self):
        with self._lock:
            self.spilled += 1

    def note_readback(self):
        with self._lock:
            self.readbacks += 1

    def ratio(self):
        with self._lock:
            return (self.readbacks / self.spilled) if self.spilled else 0.0


def disclose(text, limit=8000, spill_dir=None, label="output", stats=None):
    """Progressive disclosure: big tool outputs become a head+tail preview
    with the full body spilled to disk; the returned preview names the spill
    path so the model can read it back in slices if it truly needs to.

    Content-addressed (sha1 of the body) so repeated identical outputs share
    one spill file. Hook `stats` (a SpillStats) and count readbacks — any
    read of a path under spill_dir — to enforce the ~15% guard above.
    """
    if len(text) <= limit:
        return text
    d = spill_dir or DEFAULT_SPILL_DIR
    os.makedirs(d, exist_ok=True)
    h = hashlib.sha1(text.encode(errors="replace")).hexdigest()[:12]
    sp = os.path.join(d, f"{h}.txt")
    if not os.path.exists(sp):
        open(sp, "w", errors="replace").write(text)
    if stats is not None:
        stats.note_spill()
    head, tail = text[:3000], text[-1000:]
    return (f"{head}\n\n... [{len(text)}B total {label}; FULL OUTPUT SPILLED "
            f"TO {sp} — read it back in slices if needed] ...\n\n{tail}")
