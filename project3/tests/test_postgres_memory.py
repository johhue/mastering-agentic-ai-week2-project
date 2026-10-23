"""Opt-in mem0/pgvector integration tests with deterministic fake embeddings."""
from dataclasses import replace
import hashlib
import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from project3.config import load_environment
from project3.memory import SharedMemory
from project3.tests.test_research import settings


class FakeEmbeddings:
    """Use stable vectors so integration tests never call embedding APIs."""

    def embed(self, text, memory_action=None):
        """Map text to a deterministic, nonzero eight-dimensional vector."""
        return [float(value + 1) / 256 for value in hashlib.sha256(text.encode()).digest()[:8]]

    def embed_batch(self, texts, memory_action=None):
        """Support mem0's batch embedding interface without external calls."""
        return [self.embed(text) for text in texts]


@unittest.skipUnless(os.getenv('P3_TEST_POSTGRES') == 'true', 'Set P3_TEST_POSTGRES=true for the local pgvector integration')
class PostgresMemoryTests(unittest.TestCase):
    """Verify the real mem0 SDK, pgvector backend and PostgreSQL history adapter."""

    def test_persistent_handoff_without_sqlite(self):
        """Fresh mem0 clients recover scoped artifacts; SQLite may never connect."""
        load_environment()
        os.environ['MEM0_TELEMETRY'] = 'false'
        os.environ['MEM0_DIR'] = str(__import__('pathlib').Path(__file__).resolve().parents[1] / '.runtime/test-mem0')
        configuration = replace(settings(), database_url=os.environ['P3_DATABASE_URL'],
                                collection='p3_contract_tests')
        session_scope = 'test-session-' + uuid4().hex
        run_one, run_two = uuid4().hex, uuid4().hex
        first = second = None
        ids = []
        with patch('mem0.memory.main.EmbedderFactory.create', return_value=FakeEmbeddings()), \
             patch('mem0.memory.main.LlmFactory.create', return_value=MagicMock()), \
             patch('sqlite3.connect', side_effect=AssertionError('SQLite is forbidden')):
            try:
                first = SharedMemory(configuration)
                ids.extend(first.write('Company A', run_one, 'discovery', {'competitors': ['One', 'Two', 'Three']}))
                ids.extend(first.write('Company A', run_two, 'discovery', {'competitors': ['Different']}))
                second = SharedMemory(configuration)
                self.assertEqual(second.read('Company A', run_one, 'discovery')['competitors'], ['One', 'Two', 'Three'])
                self.assertEqual(second.read('Company A', run_two, 'discovery')['competitors'], ['Different'])
                with self.assertRaises(Exception):
                    second.read('Company B', run_one, 'discovery')
                self.assertTrue(ids)
                self.assertTrue(first.client.db.get_history(ids[0]))
                first.client.db.save_messages([{'role': 'user', 'content': 'Test context'}], session_scope)
                self.assertEqual(first.client.db.get_last_messages(session_scope)[0]['content'], 'Test context')
            finally:
                if first:
                    for memory_id in ids:
                        first.client.delete(memory_id)
                    with first.client.db.connect() as connection:
                        connection.execute('DELETE FROM p3_mem0_history WHERE memory_id = ANY(%s)', (ids,))
                        from psycopg.types.json import Jsonb
                        connection.execute('DELETE FROM p3_mem0_messages WHERE scope = %s', (Jsonb(session_scope),))
                    first.close()
                if second:
                    second.close()
