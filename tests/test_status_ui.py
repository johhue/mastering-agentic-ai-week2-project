"""Offline Streamlit behavior checks for the project-status dashboard."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


class DashboardTests(unittest.TestCase):
    """Ensure a reviewable demo works without source or OpenAI calls."""

    def test_demo_report_and_question(self):
        """Keep generated reports visible across reruns and display history evidence."""
        with patch('project2.status_agent.agent.setup_logging'), patch.dict(os.environ, {'PM_USE_LLM': 'false'}):
            app = AppTest.from_file(str(Path(__file__).resolve().parent.parent / 'bin/pm_status_app.py'), default_timeout=15).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, '3')
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Weekly project status' in entry.value for entry in app.markdown))
            app.text_input[0].input("What's been stuck for more than one sprint?")
            app.button[1].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('DEMO-12' in entry.value for entry in app.markdown))
            self.assertTrue(any('LLM synthesis is disabled' in entry.value for entry in app.markdown))
