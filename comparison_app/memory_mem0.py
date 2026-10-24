"""Hosted mem0.ai handoffs without a local database requirement."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from threading import RLock

import httpx
from utils.common import configure_logging, get_required_env
from utils.config import ROOT, ResearchError, Settings
from comparison_app.models import utc_now
from comparison_app.observability import message, log_request, log_response

log = configure_logging()


class SharedMemoryMem0:

    """Run-scoped exact agent artifacts stored in hosted mem0.ai metadata."""

    def __init__(self, settings: Settings):
        """Authenticate with mem0.ai using a bounded, observed HTTP client."""
        self.workspace = settings.workspace
        self.lock = RLock()
        self.transport = None
        os.environ['MEM0_TELEMETRY'] = 'false'
        os.environ.setdefault('MEM0_DIR', str(ROOT / 'comparison_app/.runtime/mem0'))
        try:
            from mem0 import MemoryClient
            self.transport = httpx.Client(timeout=settings.timeout,
                event_hooks={'request': [log_request], 'response': [log_response]})
            self.client = MemoryClient(api_key=settings.mem0_key, client=self.transport)
            log.info('Hosted mem0.ai memory initialized.')
        except Exception as memory_init_error:
            log.error(f"Got a memory init error: {memory_init_error}")
            if self.transport is not None:
                self.transport.close()
            raise ResearchError('Hosted mem0.ai is unavailable. Verify MEM0_API_KEY, quota and connectivity.') from memory_init_error

    def namespace(self, company: str) -> str:
        """Scope memory to a workspace and normalized company without cross-run reuse."""
        return hashlib.sha256(f'{self.workspace}:{company.strip().casefold()}'.encode()).hexdigest()

    def write(self, company: str, run_id: str, kind: str, payload: dict) -> list[str]:
        """Save an exact JSON artifact, embedding only a compact handoff descriptor.

        infer=False prevents mem0 from rewriting competitor lists or citations.
        Keeping the full artifact in metadata avoids embedding token-limit failures.
        """
        try:
            import json
            log.info(f"Writing mem0 company={company} run_id={run_id} kind={kind}...")
            log.info(f"Payload: {json.dumps(payload, indent=2)}")

            with self.lock:
                result = self.client.add([{'role': 'assistant', 'content':
                    f'Market research {kind} for {company}. Run {run_id}.'}],
                    user_id=self.namespace(company), run_id=run_id, infer=False,
                    metadata={'kind': kind, 'artifact_json': json.dumps(payload, ensure_ascii=False),
                              'observed_at': utc_now()})
            if not result.get('results'):
                raise ResearchError('mem0 did not confirm a memory write.')
            log.info('Saved %s agent artifact to shared mem0 memory.', kind)
            message('agent', 'mem0', f'Run {run_id}: saved {kind}.', payload)
            return [row['id'] for row in result['results']]
        except ResearchError as research_error:
            log.error(f"Got a research error: {research_error}.")
            raise
        except Exception as memory_write_error:
            log.error(f"Got a memory write error: {memory_write_error}.")
            raise ResearchError('Could not save the agent handoff to shared mem0 memory.') from memory_write_error

    def read(self, company: str, run_id: str, kind: str) -> dict:
        """Query mem0 using exact company, run, and artifact-type filters."""
        log.info(f"Reading mem0 ...")
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
            message('mem0', 'agent', f'Run {run_id}: retrieved {kind}.', payload)
            return payload
        except ResearchError as research_error:
            log.error(f"Got a research error: {research_error}.")
            raise
        except Exception as memory_read_error:
            log.error(f"Got a memory read error: {memory_read_error}.")
            raise ResearchError('Could not retrieve the agent handoff from shared mem0 memory.') from memory_read_error

    def close(self) -> None:
        """Release the hosted mem0 HTTP connection pool."""
        try:
            self.transport.close()
            log.info('Hosted mem0.ai client closed.')
        except Exception as memory_close_error:
            log.error(f"Got a memory close error: {memory_close_error}.")
            raise ResearchError('Could not close the mem0.ai client.') from memory_close_error
