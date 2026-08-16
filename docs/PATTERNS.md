# PATTERNS — harness integration patterns, with measured rationale

These are the design patterns behind the `kit/` modules, written up so you can
adapt them into any harness (ours is a single-file, stdlib-only agent loop;
yours can be anything). Each pattern carries the measurement that justifies it
— labels as defined in the README (CLEAN / DIRECTIONAL / ARITHMETIC).

Architecture credit: the append-only-log/derived-context spine follows the
DeepSeek Harness architecture (MIT, https://github.com/deepseek-ai/deepseek-harness)
— see docs/CREDITS.md.

---

## 1. Append-only event log; context is derived, never mutated

**Pattern.** The session is an append-only JSONL of events
(`user_message`, `assistant_message`, `tool_result`, `system_note`,
`telemetry`, effect-ledger events). The model-visible message list is
*computed* from the log by a `project()` function on every request. Trim is a
projection policy, not history surgery.

**Why.**
- Crash recovery, audit, and forking all become trivial: replay the log.
- Diet passes (dedup, compaction, elision — `kit/diet.py`) are pure functions
  of the view; a bad policy is a one-line revert, not data loss.
- Telemetry rides the same log, so every claim about the session is
  reconstructable from disk.

**Stamp every event** with a run id, turn id, and a per-log sequence number on
append (existing values pass through untouched, so forks keep their original
stamps).

## 2. Idempotent effect ledger (attempted / committed / replay)

**Pattern.** Tools with world side effects (shell, write, edit) get an
idempotency key on every call:

```
ikey = sha1(tool | canonical-json(args) | turn_id | step)[:16]
```

Execution records `effect_attempted(ikey)` *before* running and
`effect_committed(ikey, result)` only after a clean result. A key already
committed replays its recorded bytes with no re-execution. Read-only tools are
keyless by design — their safety lives in the read cache
(`kit/munch.py`), not here.

**Why.** Retries, double-emitted tool calls, and crash-restarts (pattern 3)
cannot double-apply a side effect. Declined/blocked actions ("USER DECLINED",
errors) never commit, so they correctly re-attempt later.

**Judgment call.** Keying on `(turn, step)` means the *same* command in a
later step re-executes. That is intentional: within one step a replay is
almost certainly a transport duplicate; across steps the world may have moved.

## 3. Unfinished-turn recovery — reconcile, never guess

**Pattern.** A turn is *finished* iff its request telemetry is followed by a
`turn_done`. If the last user turn has a request but no `turn_done` (process
restart, network death, request deadline), the next turn reconciles BEFORE
the new user request:

- every attempted-but-uncommitted effect of the crashed turn gets an
  `effect_reconciled(status="ambiguous")` event;
- an advisory system note names the tool and key: *"...MAY or MAY NOT have
  completed. Do NOT blindly re-run side-effecting commands; verify state
  first (re-read the file / check the output) and act accordingly."*

**Why.** The alternative binaries are both wrong: auto-rerun can double-apply
a side effect; silently skipping hides a half-applied one. "Ambiguous + model
verifies" is the only safe default. Keep the note's byte-position stable
(pattern 4) — append it at the END of the merged system message.

Pair this with a **hard per-request deadline** (a timer that closes the
response so a stalled read raises): the abort kills the turn without
`turn_done`, and this pattern catches it on the next entry. A heartbeat that
shortens stall detection is an optimization; the recovery semantics are the
watchdog.

## 4. Prefix-stability law

**Pattern.** The leading system message must be byte-identical across the
requests of a session (or at least a turn): style text leads it and never
varies; everything that varies per turn/step lands *after* stable bytes, or
at the end of the merged system block.

**Why (the arithmetic).** Our rig prefills at ~390 tok/s. A prompt-cache break
re-prefills everything: **10k tokens ≈ 26 s of time-to-first-token**
(ARITHMETIC — measured ceiling, deterministic division). A "dynamic" system
message that embeds timestamps or per-step state silently pays that on every
request. Record a telemetry event when the leading bytes change mid-turn so
the cost is attributable.

## 5. Read cache validated by mtime (`kit/munch.py`)

**Pattern.** See the module — read-only tools only; `(mtime_ns, size)`
re-validated on every hit; make-style post-execution stamp; LRU cap; TTL for
results with no file to stat; the full cached bytes flow back.

**Why.** Zero re-execution on unchanged files, and byte-identical reruns are
exactly what feeds projection dedup (`kit/diet.py`): identical bytes in,
stubbed bytes out. The token saving happens at projection; the cache's own
saving is time and determinism.

## 6. Diet at projection (`kit/diet.py`)

**Pattern.** Three view-only passes: budget elision (oldest tool bodies
first), identical-output dedup (stub references the earlier event), and
long-session compaction (old bodies stub once the log is long; the recent
working window stays full-fidelity).

**Measured.** Dedup is -66% on 3x-5KB-repeat suites (ARITHMETIC, clean);
with munch reads the exploration task's prompt fell 53.5 KB -> 4.9 KB, -91%
(CLEAN, structural, n=1).

**Progressive disclosure** completes the diet: big tool outputs become
head+tail previews with the full body spilled to a content-addressed file
whose path is named in the preview. Guard it with a **read-back counter** —
if the model re-reads spilled bytes for more than ~15% of spills, the diet is
negative-sum on that output class: raise the limit or stop spilling it.

## 7. Verify-after-edit evidence

**Pattern.** An edit tool's return value is not "ok" — it is the changed
region (a few lines of context around the hunk) plus, for source files, a
parse verdict (`ast.parse` for Python: "file still parses OK" or "SYNTAX
BROKEN: ... — FIX BEFORE ANSWERING").

**Why.** A local model that must *look at its work* stops declaring success
over broken edits. This is the Pi (pi.dev / earendil-works) local-model
infrastructure philosophy (docs/CREDITS.md): a frontier model tolerates a
sloppy setup; a local model does not — fix it with infrastructure, not vibes.

## 8. Repair-loop breaker

**Pattern.** Track the file paths touched by recent tool calls. Three or more
consecutive steps touching the same path = the model is cycling; inject a
system note forcing diff-first discipline ("re-read only the changed hunk;
edit results already show it; stop re-reading whole files") and reset the
tracker.

**Why.** Re-read loops are the classic local-model failure mode, and each
iteration re-pays prefill (pattern 4's arithmetic). The note plus the
verify-after-edit evidence (pattern 7) gives the model a cheaper true
description of state than another full read.

## 9. Bounded turns, budget notes, forced final answer

**Pattern.** A turn is at most N steps (ours: 24). At N-3, inject a budget
note ("3 tool steps remain — answer now"). At N, one final no-tools request
forces an answer instead of dying mid-loop.

**Why.** Unbounded agent loops on local hardware are effectively hangs; the
budget note converts a hard stop into a soft landing the model can steer for.

## 10. Telemetry that cannot break the task

**Pattern.** Every measurement side channel — cache hit/miss hooks, decode
rates, thermal readings, spill counters, cache-break bisectors — is wrapped
so its failure is swallowed and logged, never propagated into the tool call
or turn.

**Why.** An instrument that can fail a task measures nothing (the task failed
for the instrument's reasons). This is also what makes the honesty method in
the README cheap to adopt: refusal counters, temperature readings, and
per-request decode rates ride along on sessions that don't care.

---

## Applying the kit

Minimal integration order, by measured pay-off:

1. `kit/styles.py` — one system-message prepend (byte-stable). -36% tokens /
   -33% time on our rig (DIRECTIONAL, see README).
2. `kit/munch.py` — a `read_symbol` tool + read cache for read-only tools.
   -91% prompt bytes on exploration (CLEAN, structural, n=1).
3. `kit/diet.py` — dedup/compaction in your projection + disclose/spill on
   big outputs. -66% on repeat-heavy suites (ARITHMETIC).
4. This file's ledger + recovery patterns once your harness runs long
   unattended tasks.
5. `kit/instruments/` from day zero — no number above survives contact with
   your rig; re-measure with labels.
