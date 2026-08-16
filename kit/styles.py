"""Reasoning-style steering for thinking models.

The idea: reasoning models burn wall time thinking in patterns the task does
not need — restating the problem, narrating steps, re-deriving known facts.
A system prompt that steers the *style* of internal reasoning cuts that waste
without touching model quality, on any vendor's thinking model.

Measured on our rig (27B reasoning model, llama.cpp, Strix Halo-class): fused
style ≈ -36% reasoning tokens / ≈ -33% task time, sustained, 15/15 correct
(n=3 styled vs an n=8 baseline band, bare stack, attribution clean).
VALIDITY: DIRECTIONAL — see README.md before quoting.

Two prior-art skills, fused into one steering layer (see docs/CREDITS.md
and THIRD-PARTY-NOTICES.md for the full notices):
  - caveman  (JuliusBrussee/caveman skill, MIT, (c) 2026 Julius Brussee;
    origin of the style. rolottr/caveman-skill is a measured variant):
    terse telegraphic fragments.
  - ponytail (DietrichGebert/ponytail, MIT, (c) 2026 DietrichGebert;
    origin of the skill): lazy-senior-dev judgment ladder.

Three laws baked into this module's design:

1. STYLE STEERS VERBOSITY — NEVER A BUDGET CAP. The server-side reasoning
   budget stays the only hard backstop; nothing here truncates mid-thought.
   (We tested a pre-call "estimated thinking scale" nudge on top of this layer
   and rejected it: the estimator showed zero discrimination across task
   scales, and nudges drift toward soft caps.)

2. BYTE-STABLE POSITION. The style text must lead the leading system message
   *identically on every request in a turn* (use `prepend_stable`). A varying
   prefix is a prompt-cache break, and on local hardware that costs real
   seconds: at ~390 tok/s prefill, each 10k re-prefilled tokens ≈ 26 s of
   time-to-first-token (ARITHMETIC).

3. EXEMPT LANES. Creative work (tokens ARE the product) and instant/no-think
   turns get no style — `style_layer()` encodes this.

Regime condition (re-baseline 2026-08-16): this layer is effective where the
model would overthink (high-effort reasoning) and counterproductive at low
effort, where there is nothing to cut — harness-lane n=15/arm at effort=low
measured +65% wall for the fused style vs off, while the server-lane /
default-effort regime reproduces the -36% tok / -33% time win. Route per
session, not per turn: apply the style only to high-effort sessions, so the
byte-stable prefix (law 2) holds for the whole session. Verify per-regime on
your own rig with the battery method in kit/instruments/ (tpt_battery.py +
tpt_style.py).
"""

import re

# The three style prompts. "fused" is the shipping default in our harness.
STYLES = {
    "fused": ("THINKING STYLE — two disciplines. CAVEMAN: reason internally in "
              "short fragments, 3-8 words each; if you already know the answer, "
              "state it and stop; never re-derive what you know. PONYTAIL: "
              "lazy-senior-dev JUDGMENT — you have been paged at 3am for "
              "over-engineering; before ANY solution, run the ladder: does this "
              "need to exist at all? -> stdlib/platform already does it? -> one "
              "line? -> only then the minimum code that works. Stop at the first "
              "rung that holds. The best code is the code never written; the "
              "best reasoning is the reasoning never thought. Prefer small "
              "fixes over big fixes when the small fix works. Only the final "
              "visible answer uses normal language."),
    "caveman": ("THINKING STYLE: reason internally in short telegraphic "
                "fragments, 3-8 words each. No step-by-step narration. "
                "Confidence high -> decide and move. Only the final answer "
                "uses normal language."),
    "ponytail": ("THINKING STYLE: lazy senior developer JUDGMENT — ultra-expert "
                 "coder who has seen every over-engineered codebase and been "
                 "paged at 3am for one. Before any solution, run the ladder: "
                 "(1) does this need to exist at all? (2) stdlib/native platform "
                 "already covers it? (3) already-installed dependency solves it? "
                 "(4) can it be one line? (5) only then: the minimum code that "
                 "works. The ladder is a reflex. The best code is the code "
                 "never written. Small fix beats big fix when the small fix "
                 "works. Only the final answer uses normal language."),
}

# The judgment ladder, stated once more as a comment because it is the whole
# philosophy: the cheapest solution layer wins, in order —
#   nothing -> stdlib/platform -> existing dependency -> one line ->
#   minimum code that works.
# "The best code is the code never written; the best reasoning is the
#  reasoning never thought."

# Creative lane: style OFF where tokens are the product.
CREATIVE = re.compile(
    r"\b(story|poem|poetry|prose|screenplay|lyrics|song|novel|fiction|"
    r"creative writing|vivid|imaginative)\b", re.I)


def style_layer(text, think_mode, dial="auto"):
    """Pick the effective think-style for this turn.

    dial: "auto" (default) | a key of STYLES | "off".
    think_mode: "think" | "instant" (instant turns never get a style —
    there is no reasoning stream to steer).

    auto = fused everywhere EXCEPT the creative lane and instant turns.
    Returns a key of STYLES, or None for "no style this turn".
    """
    if dial in ("off",) or think_mode == "instant":
        return None
    if dial in STYLES:
        return dial
    if CREATIVE.search(text):
        return None
    return "fused"


def prepend_stable(system_text, style_name):
    """Apply a style byte-stably: style text LEADS the leading system message,
    so the prefix is identical every request and the prompt cache holds.
    Anything that varies per turn or per step belongs AFTER stable bytes,
    never before them."""
    return f"{STYLES[style_name]}\n\n{system_text}"
