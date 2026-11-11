from pathlib import Path
import tempfile
import unittest

from kit.munch import read_symbol


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
