# context-kit architecture

## Parts and flow

There is no daemon or application framework. The Python standard-library modules are independent building blocks; the surrounding agent owns authorization, durable history, model selection, and lifecycle.

```text
read-only tool request -> munch.read_symbol / cached_read -> full tool result
append-only history owned by caller -> diet.project -> model-visible event view
large output -> diet.disclose -> spill file + preview/path
session policy -> styles selector/prefix -> caller's system message -> model
measurement CLI -> localhost OpenAI-compatible HTTP -> simple graders -> stdout
```

[munch.py](kit/munch.py) parses Python with `ast`, returns the first matching function/class by unqualified name, and can return its line-span body (capped at 24,000 characters). Missing symbols list candidates; non-Python inputs get an explicit error. `ResultCache` is process-local, lock-protected and capacity-limited, with optional telemetry callbacks. File-backed lookups compare `mtime_ns` and size; non-file keys use age.

[diet.py](kit/diet.py) composes budget elision, identical-output deduplication, and old-result compaction, returning a new list and replacement dictionaries for changed entries. Unchanged dictionaries may still be shared. `disclose` writes large text under a caller-selected spill directory (default user cache), names files with a shortened SHA-1 digest, and returns a fixed head/tail preview. `SpillStats` counts spill/readback activity only when the caller wires it in.

[styles.py](kit/styles.py) holds literal prompts and simple routing; it does not change server reasoning budgets, inspect model effort, or persist session policy. Stable prefix placement is a caller integration contract.

[tpt_battery.py](kit/instruments/tpt_battery.py) and [tpt_style.py](kit/instruments/tpt_style.py) post to `http://127.0.0.1:PORT/v1/chat/completions` using `urllib`, with thinking requested and per-task output limits. They grade five single responses, print status/token counts and a summary, and do not execute returned code or tools.

## Risky paths and what failure looks like

- Cache keys must cover every argument that shapes output. Mtime/size are not content hashes; preserving both can hide changes, and a write during a read is not made atomic by stamping after execution. Stale data looks like a valid cache hit. Do not cache mutations or treat this as filesystem confinement.
- AST syntax/I/O errors propagate; duplicate symbol names are ambiguous; body extraction rereads the file. A symbol snippet is not guaranteed to represent one atomic file version.
- Projection is lossy by design. `elide_to_budget` uses character counts, does not count replacement text accurately as a strict cap, and retains at least eight events in its dropping phase. `dedup_identical` compares Python hash values without a second full-text equality check. Do not describe projection as a hard token budget or lossless context.
- Spills are plaintext files, not encrypted storage. Short digest names, existence checks, and direct writes are not collision/concurrency protections. Missing/unreadable files break progressive disclosure; callers own permissions, retention and sensitive-data policy.
- Style toggles can invalidate prompt caches or worsen low-effort behavior. Keep effort-aware session routing outside the per-turn helper; measure before adopting performance claims.
- Instrument network/response-shape failures can terminate the script. Code grading checks textual shape, not correctness. Summary time/tokens accumulate only for passed tasks, so failed-task cost is excluded and the printed wall figure is not total elapsed run time. Inspect failures and collect a separate full raw trace; do not promote these metrics to production evidence.

## Verification scope

Import and isolated deterministic probes can establish helper behavior without loading any model. Real server benchmarks require the host's resource policy and explicit measurement controls; none are implied by this documentation. No UI or service is changed. Rollback is reverting the documentation commit, not changing a model or deleting spill/history data.
