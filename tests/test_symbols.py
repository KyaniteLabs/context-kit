from pathlib import Path
import tempfile
import unittest
from unittest import mock

from kit.munch import Outcome, ResultCache, cached_read, read_symbol


class SymbolTests(unittest.TestCase):
    def test_signature_doc_span_and_body_share_one_source(self):
        source = ('def example(value: int, scale: int = 2) -> int:\n'
                  '    """Return scaled value."""\n'
                  '    return value * scale\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sample.py'
            path.write_text(source)
            stub = read_symbol(str(path), 'example')
            self.assertIn('def example(value: int, scale: int=2) -> int', stub)
            self.assertIn('Return scaled value.', stub)
            self.assertIn(f'{path}:1-3', stub)
            self.assertNotIn('return value * scale', stub)
            self.assertIn('return value * scale', read_symbol(str(path), 'example', True))

    def test_async_multiline_and_class_headers(self):
        source = ('async def work(\n    x: str, /, *, flag=True\n) -> str:\n'
                  '    return x\n\nclass Worker(Base):\n    pass\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sample.py'
            path.write_text(source)
            self.assertIn('async def work(x: str, /, *, flag=True) -> str',
                          read_symbol(str(path), 'work'))
            self.assertIn('class Worker(Base)', read_symbol(str(path), 'Worker'))


class ReadSymbolFailureTests(unittest.TestCase):
    """Every miss is an "ERROR: ..." string. read_symbol used to leak the
    raw SyntaxError / FileNotFoundError out of the tool call."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text)
        return str(path)

    def assertVerdict(self, out, path, line, message):
        """PATTERNS.md 7 form: what is broken, where (path:line), and the
        order to fix it before answering."""
        self.assertIsInstance(out, str, out)
        self.assertTrue(out.startswith('ERROR: SYNTAX BROKEN: '), out)
        self.assertTrue(out.endswith(' — FIX BEFORE ANSWERING'), out)
        self.assertIn(f'SYNTAX BROKEN: {path}:{line}: {message}'
                      ' — FIX BEFORE ANSWERING', out)

    def test_syntax_error_returns_the_verdict_with_path_and_line(self):
        # BUG (old code): SyntaxError: invalid syntax (<unknown>, line 1)
        path = self.write('broken.py', 'def oops(:\n')
        self.assertVerdict(read_symbol(path, 'oops'), path, 1, 'invalid syntax')

    def test_syntax_error_names_the_broken_line_with_or_without_body(self):
        path = self.write('later.py',
                          'def a():\n    return 1\n\ndef b(:\n    pass\n')
        for want_body in (False, True):
            with self.subTest(want_body=want_body):
                self.assertVerdict(read_symbol(path, 'b', want_body),
                                   path, 4, 'invalid syntax')

    def test_nul_byte_source_is_a_verdict_on_every_python(self):
        # Python 3.10 raises ValueError for this, 3.12+ a SyntaxError.
        path = self.write('nul.py', 'def fine():\x00\n    return 1\n')
        out = read_symbol(path, 'fine')
        self.assertIsInstance(out, str, out)
        self.assertTrue(out.startswith('ERROR: SYNTAX BROKEN: '), out)
        self.assertTrue(out.endswith(' — FIX BEFORE ANSWERING'), out)
        self.assertIn(path, out)
        self.assertIn('null bytes', out)

    def test_missing_file_is_an_error_string(self):
        # BUG (old code): FileNotFoundError
        path = str(self.dir / 'nonexistent' / 'nope.py')
        out = read_symbol(path, 'x')
        self.assertIsInstance(out, str, out)
        self.assertTrue(out.startswith(f'ERROR: cannot read {path}: '), out)
        self.assertIn('No such file or directory', out)

    def test_unreadable_file_is_an_error_string(self):
        # BUG (old code): PermissionError / IsADirectoryError
        path = self.write('denied.py', 'def fine():\n    return 1\n')
        denied = PermissionError(13, 'Permission denied')
        with mock.patch('builtins.open', side_effect=denied):
            out = read_symbol(path, 'fine')
        self.assertIsInstance(out, str, out)
        self.assertTrue(out.startswith(f'ERROR: cannot read {path}: '), out)
        self.assertIn('Permission denied', out)
        named_dir = self.dir / 'dir.py'              # a real unreadable target
        named_dir.mkdir()
        out = read_symbol(str(named_dir), 'x')
        self.assertIsInstance(out, str, out)
        self.assertTrue(out.startswith(f'ERROR: cannot read {named_dir}: '), out)

    def test_missing_symbol_still_lists_candidates(self):
        # Unchanged: the cheap retry the docstring promises.
        path = self.write('good.py',
                          'def fine():\n    return 1\n\n\nclass Box:\n    pass\n')
        out = read_symbol(path, 'absent')
        self.assertEqual(
            out, f"ERROR: symbol 'absent' not in {path}. Candidates: fine, Box")

    def test_non_python_target_error_is_unchanged(self):
        path = self.write('notes.txt', 'not python\n')
        self.assertEqual(read_symbol(path, 'x'),
                         'ERROR: read_symbol supports .py only '
                         '(use read_file for other types)')

    def test_cached_read_recovers_once_the_broken_file_is_fixed(self):
        # Verify-after-edit through the sibling cached_read: the verdict is
        # error text, so it is returned uncached and the next read (after
        # the edit is repaired) sees the fixed file.
        path = self.write('oops.py', 'def oops(:\n')
        cache = ResultCache()

        def tool(p):
            return read_symbol(p, 'oops')

        out = cached_read(cache, path, tool)
        self.assertTrue(out.startswith('ERROR: SYNTAX BROKEN: '), out)
        self.assertIs(cache.check(f'read|{path}', path)[0], Outcome.ABSENT)
        self.write('oops.py', 'def oops():\n    return 2\n')
        self.assertIn('def oops()', cached_read(cache, path, tool))


if __name__ == "__main__":
    unittest.main()
