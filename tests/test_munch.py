"""ResultCache entry lifecycle (kit/munch.py)."""

import os
import random
import tempfile
import unittest
from unittest import mock

from kit import munch
from kit.munch import Outcome, ResultCache, Validation


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.clock = Clock()
        p = mock.patch.object(munch, "time", self.clock)
        p.start()
        self.addCleanup(p.stop)

    def file(self, name="f.txt", text="hello"):
        path = os.path.join(self.dir.name, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def bump(self, path, text):
        st = os.stat(path)
        with open(path, "w") as f:
            f.write(text)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))


class OutcomeTable(Base):
    """Every Outcome is reachable — adding one without a test fails."""

    def test_every_outcome(self):
        seen = set()
        c = ResultCache(ttl_s=10)
        path = self.file()

        seen.add(c.check("k")[0])                          # ABSENT
        c.store("k", "v")
        o, r = c.check("k")
        self.assertEqual((o, r), (Outcome.HIT, "v"))
        seen.add(o)
        self.clock.now += 11
        seen.add(c.check("k")[0])                          # EXPIRED
        c.store("f", "body", path=path)
        self.bump(path, "changed!")
        seen.add(c.check("f", path)[0])                    # FILE_CHANGED
        c.store("f", "body", path=path)
        os.unlink(path)
        seen.add(c.check("f", path)[0])                    # FILE_GONE
        c.store("t", "v")
        seen.add(c.check("t", path)[0])                    # MODE_MISMATCH
        self.assertEqual(seen, set(Outcome))

    def test_every_miss_invalidates(self):
        c = ResultCache(ttl_s=10)
        c.store("k", "v")
        self.clock.now += 11
        self.assertIs(c.check("k")[0], Outcome.EXPIRED)
        self.assertIs(c.check("k")[0], Outcome.ABSENT)     # gone now

    def test_validation_modes_named(self):
        self.assertEqual({v.value for v in Validation}, {"file", "ttl"})


class Bugs(Base):
    def test_file_entry_looked_up_without_path_is_not_served_stale(self):
        # BUG (old code): an entry stored WITH a path but looked up with
        # path=None took the TTL branch and skipped the re-stat, serving
        # stale bytes after the file changed (breaks "validate every hit").
        path = self.file(text="old")
        c = ResultCache()
        c.store("k", "old", path=path)
        self.bump(path, "new content")
        self.assertIsNone(c.lookup("k"))

    def test_ttl_entry_looked_up_with_path_does_not_raise(self):
        # BUG (old code): KeyError 'mtime_ns' — the cache broke a tool call.
        path = self.file()
        c = ResultCache()
        c.store("read|" + path, "from-ttl")       # stored without a path
        out = munch.cached_read(c, path, lambda p: "fresh")
        self.assertEqual(out, "fresh")

    def test_hook_receives_key_and_hit(self):
        got = []
        c = ResultCache()
        c.stat_hook = lambda key, hit: got.append((key, hit))
        c.store("k", "v")
        c.lookup("k")
        self.assertEqual(got, [("k", False), ("k", True)])


class Behaviour(Base):
    def test_lru_eviction(self):
        c = ResultCache(cap=2)
        c.store("a", 1)
        self.clock.now += 1
        c.store("b", 2)
        self.clock.now += 1
        c.lookup("a")                    # touch a
        self.clock.now += 1
        c.store("c", 3)
        self.assertIsNone(c.lookup("b"))
        self.assertEqual(c.lookup("a"), 1)

    def test_cached_read(self):
        path = self.file()
        c = ResultCache()
        calls = []

        def ex(p):
            calls.append(p)
            with open(p) as f:
                return f.read()
        self.assertEqual(munch.cached_read(c, path, ex), "hello")
        self.assertEqual(munch.cached_read(c, path, ex), "hello")
        self.assertEqual(len(calls), 1)
        self.bump(path, "world!")
        self.assertEqual(munch.cached_read(c, path, ex), "world!")
        self.assertEqual(len(calls), 2)

    def test_errors_not_cached(self):
        c = ResultCache()
        path = self.file()
        munch.cached_read(c, path, lambda p: "ERROR: nope")
        self.assertIs(c.check(f"read|{path}", path)[0], Outcome.ABSENT)


class CacheModel(Base):
    """Stateful property test against a reference model."""

    def test_random_sequences(self):
        for seed in range(200):
            rng = random.Random(seed)
            cap = rng.randint(1, 4)
            c = ResultCache(cap=cap, ttl_s=5)
            paths = [self.file(f"p{i}.txt", "x") for i in range(3)]
            version = {p: 0 for p in paths}
            model = {}       # key -> (path|None, version at store, born)
            keys = ["k0", "k1", "k2", "k3", "k4"]
            for _ in range(60):
                op = rng.choice(["store", "lookup", "edit", "tick"])
                k = rng.choice(keys)
                p = rng.choice(paths + [None])
                if op == "store":
                    if p is not None and not os.path.exists(p):
                        continue
                    c.store(k, (k, p, version.get(p)), path=p)
                    model[k] = (p, version.get(p), self.clock.now)
                elif op == "edit":
                    q = rng.choice(paths)
                    version[q] += 1
                    if rng.random() < 0.2 and os.path.exists(q):
                        os.unlink(q)
                    else:
                        self.bump(q, "x" * (version[q] + 1)) \
                            if os.path.exists(q) else self.file(
                                os.path.basename(q), "y" * version[q])
                elif op == "tick":
                    self.clock.now += rng.choice([1, 3, 6])
                else:
                    outcome, res = c.check(k, p)
                    if outcome is Outcome.HIT:
                        sp, ver, born = model[k]
                        self.assertEqual(sp, p, seed)        # same mode
                        if p is None:
                            self.assertLessEqual(
                                self.clock.now - born, 5, seed)
                        else:
                            self.assertEqual(ver, version[p], seed)
                        self.assertEqual(res, (k, p, ver))
                    else:
                        model.pop(k, None)
                self.assertLessEqual(len(c._ent), cap)
                for ent in c._ent.values():
                    self.assertIn(ent["mode"], set(Validation))
                    self.assertEqual(ent["mode"] is Validation.FILE,
                                     ent["path"] is not None)


if __name__ == "__main__":
    unittest.main()
