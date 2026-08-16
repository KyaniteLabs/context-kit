# CREDITS

context-kit is a synthesis and measurement effort; the ideas stand on prior
art and on people who reviewed the numbers. Everything borrowed was re-read,
re-implemented clean, and measured on our rig (with labels — see README).

## Prior art

- **rolottr/caveman-skill** (MIT, (c) 2026 rolottr) — the caveman reasoning
  style: terse telegraphic fragments, action over explanation, "grunt the
  essentials, then answer." One of the two styles fused into `kit/styles.py`
  (prompt text adapted from the skill).
- **ponytail skill** (marmelab's published copy carries an MIT notice in its
  SKILL.md frontmatter) — the lazy-senior-dev judgment ladder ("does this
  need to exist at all? -> stdlib? -> one line? -> minimum that works"). The
  other half of `kit/styles.py`, and the philosophy comment throughout.
- **jCodeMunch / jDocMunch (jgravelle)** — the prefill attack: symbol-level
  code retrieval and section-indexed doc reads instead of whole files.
  `kit/munch.py` is a stdlib-`ast` reimplementation of the core move
  (ours is Python-only; theirs is tree-sitter and broader). Idea only —
  no upstream code is included here (upstream is under a dual-use
  non-commercial license; see THIRD-PARTY-NOTICES.md).
- **DeepSeek Harness (DSH, MIT, (c) 2026 DeepSeek)** — the architecture
  spine: append-only event log with derived model context, reversible plugin
  composition. Pattern 1 in `docs/PATTERNS.md` is DSH's best idea, kept.
- **gjc / gajae-code (Yeachan-Heo, MIT)** — workflow and context discipline:
  plan-gated mutation, artifact spill (bulky intermediates to files, not
  context). The spill/disclose half of `kit/diet.py` follows this line.
- **marks-pi-harness (Early AI Dopters, MIT)** — local-model infrastructure
  philosophy: "A frontier model tolerates a sloppy setup. A local model
  does not — fixed by infrastructure: tools that force the model to look
  at its work, gates it cannot talk past, guards that turn chaos into
  structured signals." Patterns 7-9 in `docs/PATTERNS.md` are this,
  operationalized.
- **ggml-org/llama.cpp (MIT, (c) 2023-2026 The ggml authors)** — the
  runtime every instrument in `kit/instruments/` measures against. Nothing
  in this repo produces a number without llama.cpp underneath it.
- **Unsloth (Apache-2.0)** — the UD dynamic quants (Q4_K_XL et al.) the
  measurement campaigns ran on; the dynamic-quant allocation scheme being
  benchmarked is their system. Used as-shipped, not redistributed.
- **nathanmarlor** — thermal-coupling discipline for fan-cooled
  unified-memory rigs (the reason every README number carries a thermal/
  window label, and the method rule "n>=3 per arm in one thermal window").

## Peer review

- **Sol** and **Kimi** — reviewed the measurement campaign, pressed the
  attribution and honesty requirements (refusal counters, grader
  false-negative classes, prefix-break attribution) that shaped the validity
  labels used throughout this repo. Several numbers we asked them to check
  came back "tainted as labeled, publish with the label or not at all" —
  which is exactly what this repo does.

## License note

MIT (see `LICENSE`). The upstream works above keep their own licenses and
credit; nothing proprietary from any source is included here.
