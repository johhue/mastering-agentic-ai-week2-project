"""Shared mem0 memory with PostgreSQL for vectors, history and message storage."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import logging
import os
from threading import RLock
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from project3.config import ROOT, ResearchError, Settings
from project3.models import utc_now

log = logging.getLogger(__name__)
_INIT_LOCK = RLock()


class PostgresHistory:
    """Replace mem0's SQLite history interface without creating any SQLite files."""

    def __init__(self, db_path: str):
        """Initialize history and message tables using the configured PostgreSQL DSN."""
        if not db_path.startswith(('postgresql://', 'postgres://')):
            raise ResearchError('mem0 history requires PostgreSQL.')
        self.dsn = db_path
        with self.connect() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS p3_mem0_history (
                id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, payload JSONB NOT NULL)''')
            connection.execute('''CREATE TABLE IF NOT EXISTS p3_mem0_messages (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                scope JSONB NOT NULL, messages JSONB NOT NULL)''')

    def connect(self):
        """Open a short-lived transaction with bounded connection and statement timeouts."""
        return psycopg.connect(self.dsn, connect_timeout=10, options='-c statement_timeout=15000')

    def add_history(self, memory_id, old_memory, new_memory, event, *, created_at=None,
                    updated_at=None, is_deleted=0, actor_id=None, role=None) -> None:
        """Persist mem0's audit event using parameterized SQL."""
        record = {'id': str(uuid4()), 'memory_id': memory_id, 'old_memory': old_memory,
                  'new_memory': new_memory, 'event': event, 'created_at': created_at,
                  'updated_at': updated_at, 'is_deleted': is_deleted, 'actor_id': actor_id, 'role': role}
        with self.connect() as connection:
            connection.execute('INSERT INTO p3_mem0_history(id,memory_id,payload) VALUES (%s,%s,%s)',
                               (record['id'], memory_id, Jsonb(record)))

    def get_history(self, memory_id) -> list[dict]:
        """Return the audit events for one source memory ID."""
        with self.connect() as connection:
            rows = connection.execute('SELECT payload FROM p3_mem0_history WHERE memory_id=%s', (memory_id,)).fetchall()
        return [row[0] for row in rows]

    def add_history_batch(self, records: list[dict]) -> None:
        """Persist mem0's batch history contract in one PostgreSQL transaction."""
        with self.connect() as connection:
            for record in records:
                payload = {'id': str(uuid4()), **record}
                connection.execute('INSERT INTO p3_mem0_history(id,memory_id,payload) VALUES (%s,%s,%s)',
                                   (payload['id'], payload['memory_id'], Jsonb(payload)))

    def save_messages(self, messages, filters) -> None:
        """Persist conversation context if the installed mem0 version requests it."""
        with self.connect() as connection:
            connection.execute('INSERT INTO p3_mem0_messages(scope,messages) VALUES (%s,%s)',
                               (Jsonb(filters), Jsonb(messages)))

    def get_messages(self, filters, limit=20) -> list[dict]:
        """Read bounded message context in chronological order for a matching scope."""
        with self.connect() as connection:
            rows = connection.execute('''SELECT messages FROM p3_mem0_messages WHERE scope = %s
                ORDER BY id DESC LIMIT %s''', (Jsonb(filters), limit)).fetchall()
        return [message for row in reversed(rows) for message in row[0]][-limit:]

    def get_last_messages(self, session_scope: str, limit: int = 10) -> list[dict]:
        """Match mem0 2.2.1's named recent-message retrieval contract."""
        return self.get_messages(session_scope, limit)

    def reset(self) -> None:
        """Refuse destructive whole-store resets through the application adapter."""
        raise ResearchError('Whole-store reset is disabled; manage retention explicitly in PostgreSQL.')

    def close(self) -> None:
        """Close no resources: each operation already owns a short-lived connection."""


@contextmanager
def postgres_history_backend():
    """Inject PostgreSQL at mem0 construction, restoring its module afterward.

    mem0 2.2.1 hardcodes SQLiteManager rather than offering a history provider.
    A locked, construction-only adapter prevents even a transient SQLite store.
    Runtime .reset() is intentionally not exposed. Contract-tested against the
    pinned SDK; revisit this injection when upgrading mem0.
    """
    import mem0.memory.main as module
    with _INIT_LOCK:
        original = module.SQLiteManager
        module.SQLiteManager = PostgresHistory
        try:
            yield
        finally:
            module.SQLiteManager = original


class SharedMemory:
    """Run-scoped agent handoffs in mem0, with exact typed artifacts in metadata."""

    def __init__(self, settings: Settings):
        """Configure pgvector and embeddings; do not use mem0's default Qdrant store."""
        os.environ['MEM0_TELEMETRY'] = 'false'
        os.environ.setdefault('MEM0_DIR', str(ROOT / 'project3/.runtime/mem0'))
        from mem0 import Memory
        self.workspace = settings.workspace
        self.lock = RLock()
        config = {
            'vector_store': {'provider': 'pgvector', 'config': {
                'connection_string': settings.database_url, 'collection_name': settings.collection,
                'embedding_model_dims': settings.dimensions}},
            'history_db_path': settings.database_url,
            'llm': {'provider': 'openai', 'config': {'model': settings.model,
                'api_key': settings.openai_key, 'openai_base_url': settings.base_url}},
            'embedder': {'provider': 'openai', 'config': {'model': settings.embedding_model,
                'api_key': settings.embedding_key, 'openai_base_url': settings.embedding_base_url,
                'embedding_dims': settings.dimensions}},
        }
        try:
            with postgres_history_backend():
                self.client = Memory.from_config(config)
            embedding_client = getattr(self.client.embedding_model, 'client', None)
            if embedding_client and hasattr(embedding_client, 'with_options'):
                self.client.embedding_model.client = embedding_client.with_options(timeout=settings.timeout)
            log.info('Shared mem0 PostgreSQL memory initialized.')
        except Exception as memory_init_error:
            raise ResearchError('Shared mem0 memory is unavailable. Start project3 PostgreSQL and verify P3_DATABASE_URL and embedding configuration.') from memory_init_error

    def namespace(self, company: str) -> str:
        """Scope memory to a workspace and normalized company without cross-run reuse."""
        return hashlib.sha256(f'{self.workspace}:{company.strip().casefold()}'.encode()).hexdigest()

    def write(self, company: str, run_id: str, kind: str, payload: dict) -> list[str]:
        """Save an exact JSON artifact, embedding only a compact handoff descriptor.

        infer=False prevents mem0 from rewriting competitor lists or citations.
        Keeping the full artifact in metadata avoids embedding token-limit failures.
        """
        try:
            with self.lock:
                result = self.client.add([{'role': 'assistant', 'content':
                    f'Market research {kind} for {company}. Run {run_id}.'}],
                    user_id=self.namespace(company), run_id=run_id, infer=False,
                    metadata={'kind': kind, 'artifact_json': json.dumps(payload, ensure_ascii=False),
                              'observed_at': utc_now()})
            if not result.get('results'):
                raise ResearchError('mem0 did not confirm a memory write.')
            log.info('Saved %s agent artifact to shared mem0 memory.', kind)
            return [row['id'] for row in result['results']]
        except ResearchError:
            raise
        except Exception as memory_write_error:
            raise ResearchError('Could not save the agent handoff to shared mem0 memory.') from memory_write_error

    def read(self, company: str, run_id: str, kind: str) -> dict:
        """Query mem0 using exact company, run, and artifact-type filters."""
        try:
            with self.lock:
                result = self.client.search(query=f'Market research {kind} for {company}',
                    filters={'user_id': self.namespace(company), 'run_id': run_id, 'kind': kind},
                    top_k=1, threshold=0.0, rerank=False)
            rows = result.get('results', [])
            if not rows:
                raise ResearchError(f'Shared memory has no {kind} artifact for this run.')
            metadata = rows[0].get('metadata', {})
            if metadata.get('kind') != kind:
                raise ResearchError('Shared memory returned an unexpected artifact type.')
            payload = json.loads(metadata['artifact_json'])
            log.info('Retrieved %s artifact from shared mem0 memory.', kind)
            return payload
        except ResearchError:
            raise
        except Exception as memory_read_error:
            raise ResearchError('Could not retrieve the agent handoff from shared mem0 memory.') from memory_read_error

    def close(self) -> None:
        """Release mem0 and its PostgreSQL connection pool after a run."""
        self.client.close()
        pool = getattr(self.client.vector_store, 'connection_pool', None)
        if pool and hasattr(pool, 'close'):
            pool.close()
        for component in (self.client.embedding_model, self.client.llm):
            client = getattr(component, 'client', None)
            if client and hasattr(client, 'close'):
                client.close()
