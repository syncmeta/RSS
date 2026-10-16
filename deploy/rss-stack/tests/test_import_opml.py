import contextlib
import io
import os
from pathlib import Path
import runpy
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'import_opml.py'


class ImportOpmlTests(unittest.TestCase):
    def test_preview_and_apply_skip_templates_and_do_not_disclose_keys(self):
        records = {}
        def create(**kwargs):
            key = (kwargs['feed_url'], kwargs['target_language'])
            created = key not in records
            records[key] = kwargs
            return SimpleNamespace(), created
        models = ModuleType('core.models')
        models.Feed = SimpleNamespace(objects=SimpleNamespace(get_or_create=create))
        core = ModuleType('core')
        with tempfile.TemporaryDirectory() as directory:
            opml = Path(directory) / 'input.opml'
            opml.write_text('<opml><body>'
                            '<outline title="Example" xmlUrl="https://example.org/feed?key=private-test-value"/>'
                            '<outline title="Template" xmlUrl="https://YOUR-HOST/feed"/>'
                            '<outline title="Bad" xmlUrl="file:///etc/passwd"/>'
                            '</body></opml>')
            output = io.StringIO()
            with patch.dict(sys.modules, {'core': core, 'core.models': models}), \
                 patch.dict(os.environ, {'RSS_IMPORT_OPML': str(opml), 'RSS_IMPORT_APPLY': '0'}), \
                 contextlib.redirect_stdout(output):
                runpy.run_path(str(SCRIPT))
                self.assertFalse(records)
                os.environ['RSS_IMPORT_APPLY'] = '1'
                runpy.run_path(str(SCRIPT))
                runpy.run_path(str(SCRIPT))
            self.assertEqual(len(records), 1)
            self.assertIn('CREATED: Example', output.getvalue())
            self.assertIn('EXISTS: Example', output.getvalue())
            self.assertNotIn('private-test-value', output.getvalue())
            self.assertNotIn('https://', output.getvalue())


if __name__ == '__main__':
    unittest.main()
