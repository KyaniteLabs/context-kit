# Third-Party Notices

context-kit builds on prior art. This file lists every third-party
component this repository derives from, references, or measures against,
its license (verified against the upstream repository on 2026-08-15),
and what we took. Our own code is MIT (see `LICENSE`); everything below
keeps its own license and credit.

## Adapted into this repository

### JuliusBrussee/caveman (skill) — MIT
- Source: https://github.com/JuliusBrussee/caveman
- Derived: origin of the "caveman" thinking-style used in `kit/styles.py`
  (terse telegraphic reasoning fragments). Prompt text is our adaptation;
  no upstream engine/runtime code is included. The skill is MIT; directories
  listed in that repo's LICENSING.md as Engine-linked are BSL-1.1 and are
  unused here.
- Copyright (c) 2026 Julius Brussee

### rolottr/caveman-skill — MIT
- Source: https://github.com/rolottr/caveman-skill
- Derived: a measured terse variant of the same style family; cited as
  secondary, not as the origin.
- Copyright (c) 2026 rolottr
- Permission is hereby granted, free of charge, to any person obtaining a
  copy of this software and associated documentation files (the
  "Software"), to deal in the Software without restriction, including
  without limitation the rights to use, copy, modify, merge, publish,
  distribute, sublicense, and/or sell copies of the Software, and to
  permit persons to whom the Software is furnished to do so, subject to
  the following conditions: The above copyright notice and this
  permission notice shall be included in all copies or substantial
  portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT
  WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
  THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE
  AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
  HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
  IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
  CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.

### DietrichGebert/ponytail — MIT
- Source: https://github.com/DietrichGebert/ponytail
- Derived: the "ponytail" style prompt text in `kit/styles.py` (the
  lazy-senior-dev judgment ladder) is adapted from this skill.
- Copyright (c) 2026 DietrichGebert
- Community republishes (e.g. marmelab/AIHarness `skills/ponytail/SKILL.md`)
  are copies, not the origin. Full MIT text as above, applying to the
  skill text.

## Patterns reimplemented clean (idea only — no upstream code included)

### jCodeMunch / jDocMunch (jgravelle) — dual-use license (non-commercial free tier)
- Source: https://github.com/jgravelle/jcodemunch-mcp
- License: "jCodeMunch-MCP — Dual-Use License v1.1", Copyright
  (c) 2024-2026 J. Gravelle. Non-commercial use free; NOT an OSI license.
- Derived: the *idea* of symbol-level code retrieval instead of whole-file
  reads. `kit/munch.py` is an independent stdlib-`ast` implementation
  written from scratch; no upstream code, text, or assets are included.
  Ideas are not copyrightable; we credit the origin regardless.

### DeepSeek Harness (DSH) — MIT
- Source: https://github.com/deepseek-ai/deepseek-harness
- Copyright (c) 2026 DeepSeek
- Derived: the append-only event log / derived-context architecture
  pattern (Pattern 1 in `docs/PATTERNS.md`). Reimplemented; no upstream
  code included.

### gajae-code / gjc (Yeachan-Heo) — MIT
- Source: https://github.com/Yeachan-Heo/gajae-code
- Copyright (c) 2025-2026 Yeachan-Heo and Gajae Code Contributors
- Derived: plan-gated mutation and artifact-spill discipline (the
  spill/disclose half of `kit/diet.py`). Pattern credit only; no upstream
  code included.

### Pi (earendil-works/pi) — MIT
- Source: https://pi.dev/ — https://github.com/earendil-works/pi
- Copyright (c) 2025 Mario Zechner
- Derived: the coding-agent harness this kit is written to sit under.
  Local-model infrastructure patterns (verify-after-edit, gates) follow
  community Pi setups; no upstream Pi code is included. Patterns 7-9 in
  `docs/PATTERNS.md`.

## Measured against / used as-shipped (not redistributed)

### ggml-org/llama.cpp — MIT
- Source: https://github.com/ggml-org/llama.cpp
- Copyright (c) 2023-2026 The ggml authors
- Relationship: the runtime every instrument in `kit/instruments/` measures
  against. Not redistributed here.

### Unsloth — Apache-2.0 (core package)
- Source: https://github.com/unslothai/unsloth
- Relationship: the UD dynamic quants (Q4_K_XL et al.) used as-shipped by
  the measurement campaigns documented in this repo. Not redistributed
  here.

### nathanmarlor/strix-halo-fan-control — MIT
- Source: https://github.com/nathanmarlor/strix-halo-fan-control
- Copyright (c) 2026 Nathan Marlor
- Relationship: methodological credit (thermal-window measurement
  discipline); its full redistribution notice lives in the sibling
  `evo-x2-ec` repository, which ships an adapted systemd unit.
