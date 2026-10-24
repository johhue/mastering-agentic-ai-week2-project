"""Optional real PostgreSQL integration test, isolated from application scopes."""
import os
import unittest
from uuid import uuid4
from support_app.status_agent.core import demo_history
from support_app.status_agent.memory import Memory


@unittest.skipUnless(os.getenv('PM_TEST_DATABASE_URL'), 'Set PM_TEST_DATABASE_URL to run PostgreSQL integration')
class PostgresTests(unittest.TestCase):
    """Validate persistence, idempotency, report writes and scope isolation."""

    def test_restart_and_scopes(self):
        """A fresh client must recover evidence without duplicating or leaking scope."""
        scope = 'integration-' + uuid4().hex
        memory = Memory(os.environ['PM_TEST_DATABASE_URL'], scope)
        try:
            for snapshot in demo_history():
                memory.save(snapshot)
            history = memory.history()
            memory.save(history[-1])
            restarted = Memory(os.environ['PM_TEST_DATABASE_URL'], scope)
            self.assertEqual(restarted.history(), history)
            self.assertEqual(len(restarted.history()), 3)
            self.assertEqual(Memory(os.environ['PM_TEST_DATABASE_URL'], scope + '-other').history(), [])
            restarted.save_report(history[-1], 'Test weekly report')
            with restarted.connect() as connection:
                count = connection.execute('SELECT count(*) FROM pm_reports WHERE scope=%s', (scope,)).fetchone()[0]
            self.assertEqual(count, 1)
        finally:
            with memory.connect() as connection:
                connection.execute('DELETE FROM pm_reports WHERE scope=%s', (scope,))
                connection.execute('DELETE FROM pm_snapshots WHERE scope=%s', (scope,))
