import contextlib
import io
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import patch


class InstrumentTests(unittest.TestCase):
    def test_help_exits_zero_without_network(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('tpt_battery.py', 'tpt_style.py'):
            with self.subTest(script=name):
                output = io.StringIO()
                script = root / 'kit' / 'instruments' / name
                with patch.object(sys, 'argv', [str(script), '--help']), \
                        patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')) as network, \
                        contextlib.redirect_stdout(output):
                    with self.assertRaises(SystemExit) as exit:
                        runpy.run_path(str(script), run_name='__main__')
                self.assertEqual(exit.exception.code, 0)
                self.assertIn('usage:', output.getvalue().lower())
                self.assertIn('PORT', output.getvalue())
                network.assert_not_called()

    def test_import_does_not_run_battery(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('tpt_battery.py', 'tpt_style.py'):
            with self.subTest(script=name), \
                    patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')) as network:
                runpy.run_path(str(root / 'kit' / 'instruments' / name))
                network.assert_not_called()
