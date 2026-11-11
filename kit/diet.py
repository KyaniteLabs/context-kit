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

import enum
import hashlib
import os
import re
import tempfile
import threading

DEFAULT_SPILL_DIR = os.path.expanduser("~/.cache/context-kit/spill")


# ------------------------------------------ projection stage of one event
class Stage(enum.Enum):
    """Where one tool_result body sits in the VIEW. The log never changes;
    only the projected copy moves, and it moves one way:

        FULL ──elide────> ELIDED      (budget pass; 200-char preview kept)
        FULL ──dedup────> DEDUPED     (identical to an earlier FULL body)
        FULL ──compact──> COMPACTED   (long-session compaction)

    Every stub stage is terminal: a stub is never re-stubbed (that would
    destroy the preview / the dedup pointer). The stage is not stored as a
    field — the model-visible bytes stay exactly as they always were — it
    is derived from the event by `stage_of`, the single reader.
    """
    FULL = "full"
    ELIDED = "elided"
    DEDUPED = "deduped"
    COMPACTED = "compacted"


class IllegalTransition(ValueError):
    """A projection move the Stage diagram does not allow."""


# The stub texts — byte-identical to every release so far.
_ELIDED_TEXT = "(elided)"
_DEDUP_PREFIX = "(unchanged output — identical to the earlier result at event "
_DEDUP_RE = re.compile(re.escape(_DEDUP_PREFIX) + r"(\d+)\)\Z")
_COMPACT_RE = re.compile(r"\(old result, \d+B — elided by compaction\)\Z")


def stage_of(event):
    """Derive the projection Stage of an event (non-tool_result -> FULL).
    Tolerant of legacy projections: an "(elided)" body without the
    `_elided` preview key still reads as ELIDED."""
    if event.get("kind") != "tool_result":
        return Stage.FULL
    if "_elided" in event or event.get("content") == _ELIDED_TEXT:
        return Stage.ELIDED
    body = event.get("content", "")
    if _DEDUP_RE.match(body):
        return Stage.DEDUPED
    if _COMPACT_RE.match(body):
        return Stage.COMPACTED
    return Stage.FULL


def dedup_target(event):
    """Index (0-based, in the same projected list) of the FULL body a
    DEDUPED stub points at; None for any other stage."""
    if stage_of(event) is not Stage.DEDUPED:
        return None
    return int(_DEDUP_RE.match(event["content"]).group(1)) - 1


def transition(event, to, *, target=None):
    """The one way a projected event changes stage. Returns a NEW dict
    (copy-on-write); raises IllegalTransition for any move not in the
    Stage diagram. `target` is the 0-based index of the earlier identical
    result, required for DEDUPED."""
    if event.get("kind") != "tool_result":
        raise IllegalTransition("only tool_result events have a stage")
    frm = stage_of(event)
    if frm is not Stage.FULL or to is Stage.FULL:
        raise IllegalTransition(f"{frm.name} -> {to.name} is not allowed")
    body = event.get("content", "")
    if to is Stage.ELIDED:
        return dict(event, content=_ELIDED_TEXT, _elided=body[:200])
    if to is Stage.DEDUPED:
        if target is None:
            raise IllegalTransition("DEDUPED needs the target index")
        return dict(event, content=f"{_DEDUP_PREFIX}{target + 1})")
    if to is Stage.COMPACTED:
        return dict(event, content=(
            f"(old result, {len(body)}B — elided by compaction)"))
    raise IllegalTransition(f"unknown stage {to!r}")


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
        if stage_of(keep[i]) is Stage.FULL and \
                keep[i].get("kind") == "tool_result":
            before = len(keep[i].get("content", ""))
            keep[i] = transition(keep[i], Stage.ELIDED)
            total += len(keep[i]["content"]) - before   # the stub counts too
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
        if e.get("kind") != "tool_result" or stage_of(e) is not Stage.FULL:
            continue
        body = e.get("content", "")
        if len(body) < min_body:
            continue
        h = hash(body)
        if h in seen:
            keep[idx] = transition(e, Stage.DEDUPED, target=seen[h])
        else:
            seen[h] = idx
    return keep


def compact_old(events, keep_recent=40, long_session=300, min_body=400):
    """Long-session compaction: once the log exceeds `long_session` events,
    old tool bodies (everything except the newest `keep_recent`) stub down
    regardless of char budget. Late-turn time-to-first-token is where
    prefill pain hurts most; the recent window the model is actively working
    in stays full-fidelity — including any old body that a DEDUPED stub in
    the recent window points at (compacting it would leave the model with
    no copy of output it is told it already has)."""
    if len(events) <= long_session:
        return list(events)
    keep = list(events)
    cut = len(keep) - keep_recent
    pinned = {dedup_target(e) for e in keep[max(cut, 0):]} - {None}
    for idx in range(cut):
        e = keep[idx]
        if e.get("kind") != "tool_result" or idx in pinned \
                or stage_of(e) is not Stage.FULL:
            continue
        if len(e.get("content", "")) > min_body:
            keep[idx] = transition(e, Stage.COMPACTED)
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
        _write_spill(sp, text)
    if stats is not None:
        stats.note_spill()
    head, tail = text[:3000], text[-1000:]
    return (f"{head}\n\n... [{len(text)}B total {label}; FULL OUTPUT SPILLED "
            f"TO {sp} — read it back in slices if needed] ...\n\n{tail}")


def _write_spill(sp, text):
    """Spill files have two on-disk states, ABSENT and COMPLETE; existence
    at the final path MEANS complete (disclose trusts it forever). So write
    to a temp file in the same dir and rename atomically — a crash or a
    concurrent reader can never observe a PARTIAL file at `sp`. Same bytes
    as the old direct write (same text mode, encoding and errors policy)."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(sp), suffix=".part")
    try:
        with os.fdopen(fd, "w", errors="replace") as f:
            f.write(text)
        os.replace(tmp, sp)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
