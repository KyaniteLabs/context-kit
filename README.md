# context-kit

**Context engineering for local LLM agent harnesses.**

A kit of small, measured, dependency-free modules and integration patterns for
anyone running a coding-agent harness on local llama.cpp-class hardware — any
model vendor. Everything here was built and measured on one rig: a 27B-class
reasoning model served by llama.cpp on Strix Halo-class unified memory, driving
a tool-using agent loop.

**Every number in this repo carries a validity label:**

- **CLEAN** — server-API-measured, or deterministic bytes/arithmetic; no known confound.
- **DIRECTIONAL** — small n and/or a known confound (thermal drift, single run,
  harness window). The *ordering* is claimed; the *magnitude* is soft.
- **ARITHMETIC** — deterministic math on measured inputs (bytes saved, tok/s to TTFT).

Zero dependencies. Python stdlib only. Adapt, don't install.

| Path | What it is |
|---|---|
| `kit/styles.py` | Reasoning-style steering prompts + `style_layer()` router |
| `kit/munch.py` | Symbol-level reads (stdlib `ast`) + mtime-validated read cache |
| `kit/diet.py` | Projection-time dedup/compaction + progressive-disclosure spill |
| `kit/instruments/tpt_battery.py` | Time-per-correct-task measurement battery |
| `kit/instruments/tpt_style.py` | A/B harness for the style prompts |
| `docs/PATTERNS.md` | Harness integration patterns (effect ledger, recovery, prefix law) |
| `docs/CREDITS.md` | Prior art and peer review |

---

## How do I cut reasoning tokens on a local LLM agent?

Steer the reasoning **style** with a system prompt. Never cap the budget.

> **Update (2026-08-18) — the cap verdict, from a paired experiment.** We ran
> the same 50 difficulty-enriched Omni-MATH problems under no cap, a 1024-token
> cap, and a 512-token cap (same problems per cell, cell order rotated, exact
> McNemar on paired flips). Result: **all three statistically indistinguishable**
> (uncapped-vs-512, p=0.73) — but the uncapped arm hit the output ceiling
> mid-think on 26/50 problems (median wall 367s vs 49s at the 512 cap) while
> the capped arms almost never died (1/50). The hard band (difficulty >= 5)
> scored 16% at *every* budget: capability-bound, not token-bound. Refined law:
> **style steering stays the default for cutting verbosity; a tight server-side
> budget is the backstop that also keeps the arm alive** — the uncapped model
> doesn't just waste time, it thinks itself to death against max_tokens. One
> caveat carried from design review: capped cells measure *forced* early
> termination (conclude-now injection), so if anything the true cap cost is
> lower than measured. Our harness default is now a 1024 budget; 512 when
> turn speed matters.

Reasoning models burn most of their wall time thinking out loud in patterns the
task doesn't need: restating the problem, narrating steps, re-deriving known
facts. Two style prompts fix that without touching budgets or quantization:

- **caveman** — reason internally in short telegraphic fragments (3–8 words);
  when confidence is high, decide and move.
- **ponytail** — lazy-senior-dev judgment: before any solution, run the ladder —
  *does this need to exist at all? → does the stdlib already do it? → one line? →
  only then the minimum code that works.* Stop at the first rung that holds.
- **fused** — both at once; this is the default our harness ships.

Measured on our rig (VALIDITY: **DIRECTIONAL** — n=3 styled runs vs an n=8
baseline band, same 5-task battery, thinking ON, measured on a bare stack with
no other changes so attribution is clean):

| Arm | tokens/task | time/task | correct |
|---|---|---|---|
| baseline band (n=8) | 151–313 | 8.6–15.0 s | — |
| fused style (n=3) | 117–143 | 5.8–6.8 s | 15/15 |

**≈ -36% reasoning tokens, ≈ -33% task time, sustained, 15/15 correct.**

Three laws if you adopt this:

1. **Style steers verbosity; the server-side budget stays the only hard
   backstop.** Nothing truncates mid-thought. (A separate estimate-then-think
   experiment that nudged reasoning with a pre-call size estimate was rejected
   on our rig: the estimator showed zero discrimination between task scales.)
2. **Byte-stable position.** The style text must *lead the leading system
   message* identically on every request, or you break the prompt cache (see
   below — that costs real seconds on local hardware).
3. **Exempt lanes.** Creative work (tokens are the product) and instant/no-think
   turns get no style.

To A/B it yourself: `python kit/instruments/tpt_style.py PORT TAG fused` vs
`TAG -` (baseline). Run **n≥3 per arm in one thermal window**, and read
[How do I measure honestly?](#how-do-i-measure-my-agent-honestly) before
believing your own numbers.

> **A warning from our own audit:** a much bigger **-51%** wall-time figure
> floats around our logs. It is a **stack delta** (n=1, style + tool payload +
> system prompt all changed at once; VALIDITY: DIRECTIONAL *as a stack number*,
> invalid as a style number). Never cite it as style steering. The -36%/-33%
> above is the clean attribution.

> **Update (2026-08-16) — the regime condition, from our own re-baseline.**
> The -36%/-33% above is real but **regime-conditional, not universal**: it
> was measured server-lane with the model's default (high) thinking effort.
> Re-measured harness-lane at low effort (n=15/arm interleaved, fixed
> fingerprinted harness), the same fused style measured **+65% wall** — a
> full inversion — because at low effort there is nothing to cut and the
> style text costs more than it saves. The rule: style steering is
> **effective where the model would overthink (high-effort reasoning), and
> counterproductive at low effort.** So **route per session, not per turn** —
> apply the style only to high-effort sessions, which also keeps the
> byte-stable prefix law intact (toggling style per turn would break the
> prompt cache mid-session). The battery method in `kit/instruments/`
> (`tpt_battery.py` + `tpt_style.py`) is how to verify this per-regime on
> your own rig before adopting. Source: re-baseline experiment log
> (REBASELINE-RESULTS.md + VALIDITY-MAP.md, 2026-08-15/16 night).

## How do I stop my agent re-reading files?

Three layers, biggest first. All in `kit/munch.py` and `kit/diet.py`.

1. **Symbol-level reads ("munch").** Agents explore by reading whole files; a
   `read_symbol` tool built on stdlib `ast` returns one function/class
   (signature, docstring, line span, optional body) instead. On our exploration
   suite: **-98% tool-result bytes (13,917 B → 276 B) and -91% prompt bytes
   (53.5 KB → 4.9 KB)** for the same task (VALIDITY: **CLEAN**, structural —
   bytes are deterministic whole-file-vs-stub, n=1). Wall time on the
   exploration task fell 48.6 s → 22.6 s (VALIDITY: **DIRECTIONAL** — n=1,
   measured inside a harness window later found to be distorting tool calls).
2. **mtime-validated read cache.** A repeat read of an *unchanged* file
   (`mtime_ns` + size match) returns the cached bytes with zero re-execution.
   Laws: read-only tools only — side-effecting tools are never cached (the
   effect ledger owns those, see `docs/PATTERNS.md`); the *full* cached bytes
   still flow back to the model.
3. **Projection-time dedup.** Identical repeated tool outputs collapse to a
   stub ("unchanged output — identical to the earlier result at event N") when
   the context is projected for the model. History keeps everything; only the
   view slims. Three 5 KB repeats of one command project to ~5.1 KB instead of
   15 KB = **-66%** on that class of repetition (VALIDITY: **ARITHMETIC**,
   deterministic).

Why bytes matter more than you think: decode gets the headlines, but **prefill
pays the bills**. At our ~390 tok/s prefill ceiling, every 10k tokens you don't
re-send saves ~26 s of time-to-first-token (VALIDITY: **ARITHMETIC** — and the
reason the prefix-stability law in `docs/PATTERNS.md` exists).

## How do I measure my agent honestly?

Measure **seconds-per-correct-task** and **tokens-per-correct-task**, not
tokens-per-second. Faster tokens don't help if the tokens are dumber and you
need more of them.

The battery (`kit/instruments/tpt_battery.py`): 5 fixed, auto-graded, single-
iteration tasks — arithmetic reasoning, strict JSON emission, a tool-call shape
check, a small coding task, and a classic trap riddle — all with thinking ON,
hit directly against the server's OpenAI-compatible API (no harness in the
path). On our rig: **7.6–7.7 s per correct task** at ~170 completion tokens mean
(VALIDITY: **DIRECTIONAL**, n=2).

Method rules, each learned by publishing a number we later had to walk back:

- **n≥3 per arm, one thermal window.** On fan-cooled unified-memory silicon,
  back-to-back runs drift with temperature; interleave arms and couple a
  temperature reading into the ledger, or your +5% is weather.
- **Count refusals.** A config that makes the model refuse tool calls inflates
  its opponent's numbers invisibly. Keep a refusal counter per arm.
- **Inspect every FAIL.** Graders under-count: a position-anchored
  `startswith("9")` riddle grader failed a *correct* answer because a code
  fence preceded the "9"; budget-truncation zero-content runs are measurement
  artifacts, not model failures. Fence-strip before grading; eyeball the FAIL
  content before you publish a pass count.
- **Label your n on every number you keep.** One unlabeled n=1 becomes a
  headline within a week. Corollary: a single-sample instrument is
  **pilot-class** — it can choose the next experiment, never an adoption or
  "crossover" decision (we caught our own one-generation config comparison
  about to do exactly that).
- **Audit the server's defaults before you trust your control arm.** We ran
  a thinking-budget experiment whose "uncapped" cell silently inherited the
  server's `--reasoning-budget 2048` default — the control arm was capped
  all along. The tell: six problems produced *byte-identical* reasoning
  lengths across the "uncapped" and 2048 cells (same cap, same greedy
  generation). Rule: read the live server cmdline for any default on your
  experiment's axis (budget, effort kwargs, sampling), and have control arms
  send explicit overrides instead of omitting fields.
- **Persist the full raw trace per row** (reasoning + final content), not
  just counts and grades. A completed 69-row run stored `think_ch`-style
  counts only; when we later needed failure-mode analysis, the evidence was
  gone. Counts are for dashboards; rows are for autopsies.
- **Measure at the source.** A client-side token estimate told us a
  tools-as-code mode cut ~10%; the server-reported prompt-token count said
  **-41.5%** — the estimate was structurally blind to the ~2100-token tool
  payload riding every request. Wire truth lives in the server's own usage
  numbers, not in what your client thinks it sent (n=180-run A/B, paired
  tasks).

## Why is decode tok/s the wrong metric?

Because on agent workloads it moves for reasons that have nothing to do with
the work. Same rig, same server, three configurations — all server-API
measured:

| Configuration | Decode tok/s | What the number actually is |
|---|---|---|
| Q4-class quant, cold prompt, ~30k ctx | 59.7 | **CLEAN** — n=3 median, thermally uncoupled |
| Q3-class quant, cold prompt, 128k ctx | 63–64 | **DIRECTIONAL** — the +5.5% over Q4 is the same scale as thermal swing; ordering holds, magnitude soft |
| Q4-class quant, warm repeat prompts | 148–163 | n-gram cache artifact — 2.4× the cold number; the label *is* the claim |

A 2.4× swing from prompt warmth alone; a full quant rung buys ~5%, which is
inside thermal noise. Meanwhile, steering reasoning tokens cut total task
*time* by ~33% with zero hardware change (DIRECTIONAL, above). On local agent
hardware: **tokens-not-needed beats tokens-per-second.** Track
seconds-per-correct-task and watch your prefill bytes.

## Community results — post your numbers

The kit is hardware-agnostic — anything running a local llama.cpp-class
server works. Our row (the rig every number in this repo was measured on) is
below; the other classes are open. **PR or issue your row —
`kit/instruments/tpt_battery.py` makes it one command** against a running
server (5 auto-graded tasks, seconds/tokens per correct task).

| Hardware | Backend/build | Config | Cold tok/s | Warm tok/s | Real-traffic band | Time-per-task | Source |
|---|---|---|---|---|---|---|---|
| AMD Ryzen AI Max+ 395 / Radeon 8060S (gfx1151, 96GB unified, GTT 64GB) | llama.cpp b10435-era (9d57ce4), ROCm/HIP | Qwen3.8-27B UD-Q4_K_XL @ **262,144 ctx** (native ceiling), **K+V q4_0** KV (champion since 2026-08-18: paired GSM8K p=1.0, zero tripwires at ~198k-tok depth; q8_0 row historical), `draft-mtp,ngram-mod` n12 / n-min 24 | 59.7 (c30) | 148–163 (repetition-assisted — ngram replays repeat/pattern traffic) | prose 20–26 effective (instrument-labeled 2026-08-18), code 30–40 | 7.9–14.3 s/task, median 11.3 (5-task battery, n=3, thermal band) | [qwen38-27b-strix-halo](https://github.com/KyaniteLabs/qwen38-27b-strix-halo) |
| Apple M4-class (unified memory) | — | — | [UNMEASURED — CONTRIBUTE] | [UNMEASURED — CONTRIBUTE] | [UNMEASURED — CONTRIBUTE] | [UNMEASURED — CONTRIBUTE] | — |
| Snapdragon X Elite-class | — | — | [UNMEASURED — CONTRIBUTE] | [UNMEASURED — CONTRIBUTE] | [UNMEASURED — CONTRIBUTE] | [UNMEASURED — CONTRIBUTE] | — |
| Intel Arc / Lunar Lake-class | — | — | [UNMEASURED — CONTRIBUTE] | [UNMEASURED — CONTRIBUTE] | [UNMEASURED — CONTRIBUTE] | [UNMEASURED — CONTRIBUTE] | — |

Same label rules we hold ourselves to (see
[How do I measure my agent honestly?](#how-do-i-measure-my-agent-honestly)):
warm c30 under ngram is a repetition artifact — the label is part of the
number; n>=3 per arm in one thermal window; time-per-task beats decode tok/s
as the headline metric. On this stack, style steering (`kit/styles.py`) moved
task time −33% with zero hardware change — expect your interesting deltas on
the same axis.

---

## License & credits

MIT — see `LICENSE`. Prior art and the people who reviewed these measurements:
`docs/CREDITS.md`.
