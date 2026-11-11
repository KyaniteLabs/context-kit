"""Projection-stage machine (kit/diet.py) + spill-file states."""

import copy
import os
import random
import tempfile
import unittest
from unittest import mock

from kit import diet
from kit.diet import IllegalTransition, Stage, stage_of, transition
from kit.diet import elide_to_budget, project


def tr(body, **kw):
    return dict(kind="tool_result", content=body, **kw)


# One sample event per stage — MUST cover every Stage member.
SAMPLES = {
    Stage.FULL: tr("x" * 500),
    Stage.ELIDED: transition(tr("y" * 500), Stage.ELIDED),
    Stage.DEDUPED: transition(tr("z" * 500), Stage.DEDUPED, target=3),
    Stage.COMPACTED: transition(tr("w" * 500), Stage.COMPACTED),
}


class StageTable(unittest.TestCase):
    def test_samples_exhaustive_over_enum(self):
        self.assertEqual(set(SAMPLES), set(Stage))

    def test_derived_stage_table(self):
        for st, ev in SAMPLES.items():
            self.assertIs(stage_of(ev), st, st)

    def test_non_tool_result_is_full(self):
        self.assertIs(stage_of({"kind": "user", "content": "(elided)"}),
                      Stage.FULL)

    def test_stub_bytes_unchanged(self):
        # Model-visible bytes are the persisted contract: byte-identical.
        self.assertEqual(SAMPLES[Stage.ELIDED]["content"], "(elided)")
        self.assertEqual(SAMPLES[Stage.ELIDED]["_elided"], "y" * 200)
        self.assertEqual(
            SAMPLES[Stage.DEDUPED]["content"],
            "(unchanged output — identical to the earlier result at event 4)")
        self.assertEqual(SAMPLES[Stage.COMPACTED]["content"],
                         "(old result, 500B — elided by compaction)")

    def test_legacy_elided_without_preview_key(self):
        self.assertIs(stage_of(tr("(elided)")), Stage.ELIDED)

    def test_dedup_target(self):
        self.assertEqual(diet.dedup_target(SAMPLES[Stage.DEDUPED]), 3)
        for st in set(Stage) - {Stage.DEDUPED}:
            self.assertIsNone(diet.dedup_target(SAMPLES[st]))


class Transitions(unittest.TestCase):
    def test_every_pair(self):
        legal = {(Stage.FULL, s) for s in Stage} - {(Stage.FULL, Stage.FULL)}
        for frm in Stage:
            for to in Stage:
                ev = SAMPLES[frm]
                if (frm, to) in legal:
                    out = transition(ev, to, target=0)
                    self.assertIs(stage_of(out), to)
                    self.assertIsNot(out, ev)          # copy-on-write
                else:
                    with self.assertRaises(IllegalTransition, msg=(frm, to)):
                        transition(ev, to, target=0)

    def test_non_tool_result_refused(self):
        with self.assertRaises(IllegalTransition):
            transition({"kind": "user", "content": "hi"}, Stage.ELIDED)

    def test_dedup_needs_target(self):
        with self.assertRaises(IllegalTransition):
            transition(tr("a" * 300), Stage.DEDUPED)


class Bugs(unittest.TestCase):
    def test_compaction_keeps_body_a_recent_dedup_stub_points_at(self):
        # BUG (old code): event 0 is the first copy of X, event 299 a repeat.
        # dedup stubs 299 -> "identical to event 1"; compaction then stubs
        # event 0 -> the model holds NO copy of X anywhere.
        body = "X" * 500
        events = [tr(body)] + [tr(f"e{i}") for i in range(298)] + [tr(body)]
        events.append(tr("tail"))
        out = diet.project(events)
        self.assertIs(stage_of(out[299]), Stage.DEDUPED)
        self.assertEqual(diet.dedup_target(out[299]), 0)
        self.assertEqual(out[0]["content"], body)

    def test_elision_counts_the_stub_against_the_budget(self):
        # BUG (old code): the "(elided)" stub was never counted, so the
        # projection could exceed the budget while dropping nothing.
        events = [tr("b" * 100) for _ in range(20)]
        out = diet.elide_to_budget(events, budget_chars=100)
        self.assertLessEqual(sum(len(e["content"]) for e in out), 100)

    def test_reelision_keeps_original_preview(self):
        # BUG (old code): eliding an already-ELIDED event overwrote the
        # 200-char preview with "(elided)".
        once = diet.elide_to_budget([tr("p" * 1000), tr("q" * 10)], 50)
        # 17 forces a second pass over the ELIDED head without dropping it
        # (the fix removed the old keep-8 floor, so tiny budgets now drop).
        twice = diet.elide_to_budget(once, 17)
        self.assertEqual(twice[0]["_elided"], "p" * 200)

    def test_crashed_spill_write_is_not_trusted_forever(self):
        # BUG (old code): a crash mid-write left a partial file at the final
        # path; disclose treats "exists" as "complete" and never rewrote it.
        text = "s" * 20000
        real_open, real_fdopen = open, os.fdopen

        def half_writer(opener):
            def wrapped(*a, **kw):
                f = opener(*a, **kw)
                orig = f.write

                def write(s):
                    orig(s[: len(s) // 2])
                    f.flush()
                    raise OSError("disk full")
                f.write = write
                return f
            return wrapped

        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(diet, "open", half_writer(real_open),
                                   create=True), \
                    mock.patch("os.fdopen", half_writer(real_fdopen)):
                with self.assertRaises(OSError):
                    diet.disclose(text, spill_dir=d)
            diet.disclose(text, spill_dir=d)
            files = os.listdir(d)
            self.assertEqual(len(files), 1, files)       # no stray temp
            with open(os.path.join(d, files[0])) as f:
                self.assertEqual(f.read(), text)


class Disclose(unittest.TestCase):
    def test_small_text_passthrough(self):
        self.assertEqual(diet.disclose("hi", limit=10), "hi")

    def test_spill_and_stats(self):
        stats = diet.SpillStats()
        with tempfile.TemporaryDirectory() as d:
            out = diet.disclose("a" * 9000, spill_dir=d, stats=stats)
            out2 = diet.disclose("a" * 9000, spill_dir=d, stats=stats)
            self.assertEqual(out, out2)
            self.assertIn("FULL OUTPUT SPILLED", out)
            self.assertEqual(len(os.listdir(d)), 1)
        self.assertEqual(stats.spilled, 2)


class ProjectionModel(unittest.TestCase):
    """Stateful property test: random sequences of passes over an evolving
    view; invariants checked after every step."""

    def test_random_pass_sequences(self):
        for seed in range(150):
            rng = random.Random(seed)
            bodies = ["A" * 450, "B" * 250, "C" * 50, "D" * 900]
            log = []
            for i in range(rng.randint(1, 340)):
                if rng.random() < 0.2:
                    log.append({"kind": "user", "content": f"u{i}", "id": i})
                else:
                    log.append(tr(rng.choice(bodies), id=i))
            snapshot = copy.deepcopy(log)
            orig = {e["id"]: e for e in log}
            first = {}                       # id -> first stub seen
            view = log
            for _ in range(rng.randint(1, 6)):
                step = rng.choice(["elide", "dedup", "compact", "project"])
                if step == "elide":
                    view = diet.elide_to_budget(view, rng.randint(0, 60000))
                elif step == "dedup":
                    view = diet.dedup_identical(view, rng.choice([1, 200]))
                elif step == "compact":
                    view = diet.compact_old(view, keep_recent=rng.randint(
                        0, 60), long_session=rng.randint(0, 320))
                else:
                    view = diet.project(view, rng.randint(1000, 400000))
                self.assertEqual(log, snapshot, seed)   # log untouched
                for e in view:
                    st = stage_of(e)
                    self.assertIn(st, set(Stage))
                    if e["kind"] != "tool_result":
                        self.assertEqual(e, orig[e["id"]])
                        continue
                    if st is Stage.FULL:
                        self.assertNotIn(e["id"], first, seed)  # one-way
                        self.assertEqual(e["content"],
                                         orig[e["id"]]["content"])
                        continue
                    # a stub never changes again once made
                    first.setdefault(e["id"], e)
                    self.assertEqual(first[e["id"]], e, (seed, step))
                    if st is Stage.ELIDED:
                        self.assertEqual(
                            e["_elided"], orig[e["id"]]["content"][:200])

    def test_single_projection_dedup_pointers_resolve(self):
        for seed in range(100):
            rng = random.Random(seed)
            bodies = ["A" * 450, "B" * 250, "D" * 900]
            log = [tr(rng.choice(bodies)) for _ in range(rng.randint(1, 340))]
            out = diet.project(log, budget_chars=10**9)
            for e in out[-40:]:
                t = diet.dedup_target(e)
                if t is not None:
                    self.assertIs(stage_of(out[t]), Stage.FULL, seed)


class BudgetTests(unittest.TestCase):
    def test_equal_width_boundary(self):
        events = [{'kind': 'tool_result', 'content': f'{i:02d}' + 'x' * 998}
                  for i in range(12)]
        original = copy.deepcopy(events)
        for fn in (elide_to_budget, project):
            with self.subTest(fn=fn.__name__):
                result = fn(events, budget_chars=1000)
                self.assertLessEqual(sum(len(e.get('content', '')) for e in result), 1000)
        self.assertEqual(events, original)

    def test_small_budgets_drop_oldest_events(self):
        for fn in (elide_to_budget, project):
            for budget in (0, 1, 7, 8, 9, 99):
                for kind in ('tool_result', 'user'):
                    with self.subTest(fn=fn.__name__, budget=budget, kind=kind):
                        events = [{'kind': kind, 'content': 'x' * 100} for _ in range(8)]
                        result = fn(events, budget_chars=budget)
                        self.assertLessEqual(sum(len(e['content']) for e in result), budget)

    def test_expanding_dedup_stubs_still_fit(self):
        events = [{'kind': 'tool_result', 'content': 'x'} for _ in range(2)]
        result = project(events, budget_chars=2, min_body=0)
        self.assertLessEqual(sum(len(e['content']) for e in result), 2)

    def test_negative_budget_rejected(self):
        for fn in (elide_to_budget, project):
            with self.assertRaises(ValueError):
                fn([], budget_chars=-1)

    def test_fitting_events_preserved(self):
        events = [{'kind': 'user', 'content': 'hello'}]
        self.assertEqual(elide_to_budget(events, 5), events)

if __name__ == "__main__":
    unittest.main()
