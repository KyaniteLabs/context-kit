# context-kit

A small Python standard-library toolkit for people integrating local LLM coding-agent harnesses. It aims to reduce unnecessary context and reasoning work while measuring useful task completion rather than headline token speed. It is a set of modules to adapt, not an installed agent, model server, or hosted product.

## Core experience and existing pieces

A harness author imports the helpers, wires them into read-only tool dispatch and context projection, and compares behavior on their own workload:

- [kit/munch.py](kit/munch.py): AST-based reads of a named Python function/class, optional source body, and an in-memory read-result cache validated by file mtime/size or TTL. Cache only read-only operations; cached full results remain available.
- [kit/diet.py](kit/diet.py): view-only budget elision, repeated tool-output stubs, old-result compaction, and head/tail previews with full text spilled to disk. It does not implement a durable event log; the host harness must retain the originals.
- [kit/styles.py](kit/styles.py): `caveman`, `ponytail`, and `fused` reasoning-style prompts, a selector that exempts instant/creative turns, and stable system-prefix composition. Effort/session policy remains the caller's responsibility.
- [kit/instruments](kit/instruments): two command-line measurement scripts targeting a local OpenAI-compatible endpoint, one baseline battery and one style comparison. Each embeds five fixed tasks: arithmetic reasoning, strict JSON, tool-call shape, code-shape, and a riddle. These are tiny diagnostic probes, not a comprehensive capability benchmark or executable code-correctness suite.
- [docs/PATTERNS.md](docs/PATTERNS.md): integration advice; [docs/CREDITS.md](docs/CREDITS.md) and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md): prior art and notices.

No web UI, MCP server, packaged datasets, dependency manifest, or automatic harness integration is present. The only bundled evaluation corpus is the five hardcoded tasks in each instrument.

## Limits

README performance figures describe historical experiments with explicit validity labels and hardware/regime caveats; they are not guarantees or measurements rerun for this documentation. The README reports style gains in one high-effort regime and regression at low effort. `style_layer()` does not detect model effort or enforce session-stable routing: integration must do that.

The measurement scripts print summaries and short failure excerpts, not a durable full-trace ledger. Correct-looking summary output is insufficient evidence of model quality. No real model benchmark or user-side recording is claimed here.
