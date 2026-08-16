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
  headline within a week.

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

---

## License & credits

MIT — see `LICENSE`. Prior art and the people who reviewed these measurements:
`docs/CREDITS.md`.
