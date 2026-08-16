#!/usr/bin/env python3
"""Style A/B — the time-per-task battery with a reasoning-STYLE system prompt.
Measures what style steering actually buys: tokens-per-correct-task and
seconds-per-correct-task vs a no-system-message baseline.
Usage: python kit/instruments/tpt_style.py PORT TAG MARKER
  MARKER: - (baseline, no system msg) | caveman | ponytail | fused
  Style texts are imported from kit/styles.py (single canonical copy —
  run from the repo root, or copy kit/ alongside this file).
Honesty: n>=3 per arm in ONE thermal window; interleave arms; keep the
baseline band wide (ours spanned 151-313 tok) before trusting a delta.
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))
from kit.styles import STYLES  # noqa: E402

MARKERS = {"-": None, **{k: k for k in STYLES}}

PORT = sys.argv[1] if len(sys.argv) > 1 else "8080"
TAG = sys.argv[2] if len(sys.argv) > 2 else "run"
MARK = sys.argv[3] if len(sys.argv) > 3 else "-"
if MARK not in MARKERS:
    sys.exit(f"MARKER must be one of: {'/'.join(MARKERS)}")
sysmsg = STYLES[MARKERS[MARK]] if MARKERS[MARK] else None
URL = f"http://127.0.0.1:{PORT}/v1/chat/completions"

TOOLS = [{"type": "function", "function": {
    "name": "read_file", "description": "Read a file from disk",
    "parameters": {"type": "object",
                   "properties": {"path": {"type": "string"}},
                   "required": ["path"]}}}]


def run(messages, max_tokens, tools=None):
    body = {"messages": messages, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": True}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        j = json.load(r)
    return (time.time() - t0, j["choices"][0]["message"].get("content") or "",
            j["choices"][0]["message"].get("tool_calls"), j.get("usage", {}))


def g_reason(c, tc, u):
    cc = c.replace(",", ".").replace(" ", "")
    return ("neither" in c.lower()
            and ("9.5" in cc or "19/2" in cc or "9\u00bd" in c))


def g_json(c, tc, u):
    try:
        return json.loads(c.strip()) == {"status": "ok", "items": [1, 2, 3]}
    except Exception:
        return False


def g_tool(c, tc, u):
    if not tc:
        return False
    try:
        f = tc[0]["function"] if isinstance(tc[0], dict) else tc[0].function
        name = f["name"] if isinstance(f, dict) else f.name
        args = f["arguments"] if isinstance(f, dict) else f.arguments
        return name == "read_file" and json.loads(args).get("path") == "/tmp/notes.txt"
    except Exception:
        return False


def g_code(c, tc, u):
    return ("def longest_palindrome" in c and "return" in c
            and ("while" in c or "for" in c))


def g_riddle(c, tc, u):
    # Fence-strip before anchoring — see the grader-artifact note in
    # tpt_battery.py (position-anchored graders under-count).
    import re
    t = re.sub(r"```.*?```", "", c, flags=re.S).strip()
    return t.startswith("9")


TASKS = [
    ("reason", g_reason,
     "Compute 9+10, then multiply by 0.5, then tell me if the final result is odd or even. Show each step.",
     800, None),
    ("json", g_json,
     'Return ONLY valid JSON, no other text: {"status": "ok", "items": [1, 2, 3]}',
     600, None),
    ("tool", g_tool,
     "Use the read_file tool to read /tmp/notes.txt", 800, TOOLS),
    ("code", g_code,
     "Write a Python function longest_palindrome(s) that returns the longest palindromic substring. Include a one-line comment on the approach.",
     1600, None),
    ("riddle", g_riddle,
     "A farmer has 17 sheep. All but 9 run away. How many sheep does he have left? Answer with the number first, then one sentence why.",
     800, None),
]

total_t = total_tok = passed = 0
for tag, grader, q, mt, tools in TASKS:
    msgs = ([{"role": "system", "content": sysmsg}] if sysmsg else []) + \
           [{"role": "user", "content": q}]
    dt, c, tc, u = run(msgs, mt, tools)
    ok = grader(c, tc, u)
    comp = u.get("completion_tokens", 0)
    if ok:
        passed += 1
        total_t += dt
        total_tok += comp
    print(f"{TAG}/{MARK} {tag}: {'PASS' if ok else 'FAIL'}  {dt:.1f}s  tok={comp}")
    if not ok:
        print(f"  FAIL-CONTENT: {c[:160]!r}")

print(f"{TAG} SUMMARY[{MARK}]: {passed}/5 | "
      f"{total_t / max(passed, 1):.1f}s/task | "
      f"{total_tok / max(passed, 1):.0f} tok/task | wall {total_t:.1f}s")
