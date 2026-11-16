import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec('streamlit'), 'Streamlit is not installed.')
class UITests(unittest.TestCase):
    def test_initial_screen_renders_without_credentials_or_network(self):
        from streamlit.testing.v1 import AppTest
        path = Path(__file__).resolve().parents[1] / 'app.py'
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'STUDIO_DATA_DIR': directory}), patch('studio.secrets.read', return_value=''):
                app = AppTest.from_file(str(path)).run(timeout=30)
                self.assertEqual(len(app.exception), 0, str(app.exception))
                self.assertEqual(len(app.tabs), 5)
                self.assertEqual(app.radio[0].value, 'mock')
                # Switching to real mode alone must not submit an API request.
                app.radio[0].set_value('real').run(timeout=30)
                self.assertEqual(len(app.exception), 0, str(app.exception))


if __name__ == '__main__':
    unittest.main()
