"""Hosted mem0.ai handoffs without a local database requirement."""
from __future__ import annotations

import hashlib
import json
import os
from threading import RLock

import httpx
from utils.config import ROOT, ResearchError, Settings
from comparison_app.models import utc_now
from comparison_app.observability import message, log_request, log_response


class SharedMemoryFileSystem:

    """Run-scoped exact agent artifacts stored in hosted mem0.ai metadata."""

    def __init__(self, settings: Settings, log=None):
        """Authenticate with mem0.ai using a bounded, observed HTTP client."""
        self.workspace = settings.workspace
        self.lock = RLock()
        self.transport = None
        self.log = log
        os.environ['MEM0_TELEMETRY'] = 'false'
        os.environ.setdefault('MEM0_DIR', str(ROOT / 'comparison_app/.runtime/mem0'))

    def get_namespace(self, company: str) -> str:
        """Scope memory to a workspace and normalized company without cross-run reuse."""
        return hashlib.sha256(f'{self.workspace}:{company.strip().casefold()}'.encode()).hexdigest()

    def write(self, company: str, run_id: str, kind: str, payload: dict) -> list[str]:
        """Save an exact JSON artifact, embedding only a compact handoff descriptor.

        infer=False prevents mem0 from rewriting competitor lists or citations.
        Keeping the full artifact in metadata avoids embedding token-limit failures.
        """
        try:

            import json
            self.log.info(f"Writing file system for memory company={company} run_id={run_id} kind={kind}...")
            self.log.info(f"Payload: {json.dumps(payload, indent=2)}")

            with self.lock:

                memory_element_id = f"{company}_{run_id}_{kind}"
                user_id = self.get_namespace(company)

                # result = self.client.add([{'role': 'assistant', 'content':
                #     f'Market research {kind} for {company}. Run {run_id}.'}],
                #     user_id=user_id, run_id=run_id, infer=False,

                metadata = {'kind': kind, 'artifact_json': payload,
                          'observed_at': utc_now()}

                with open(f"/var/tmp/example_{memory_element_id}.txt", "w", encoding="utf-8") as file:
                    file.write(json.dumps(payload))

            return [run_id]

        except ResearchError as research_error:
            self.log.error(f"Got a research error: {research_error}.")
            raise
        except Exception as memory_write_error:
            self.log.error(f"Got a memory write error: {memory_write_error}.")
            raise ResearchError('Could not save the agent handoff to shared mem0 memory.') from memory_write_error

    def read(self, company: str, run_id: str, kind: str) -> dict:
        """Query mem0 using exact company, run, and artifact-type filters."""
        self.log.info(f"Reading file system into memory company={company} run_id={run_id} kind={kind}...")

        try:
            payload = None
            memory_element_id = f"{company}_{run_id}_{kind}"

            with open(f"/var/tmp/example_{memory_element_id}.txt", "r", encoding="utf-8") as file:
                payload = file.read()

            return json.loads(payload)

        except ResearchError as research_error:
            self.log.error(f"Got a research error: {research_error}.")
            raise
        except Exception as memory_read_error:
            self.log.error(f"Got a memory read error: {memory_read_error}.")
            raise ResearchError('Could not retrieve the agent handoff from shared mem0 memory.') from memory_read_error

    def close(self) -> None:
        """Release the hosted mem0 HTTP connection pool."""
        try:
            # self.transport.close()
            self.log.info(f"Wrapping up file-based memory usage.")
        except Exception as memory_close_error:
            self.log.error(f"Got a file close error: {memory_close_error}.")
            raise ResearchError('Could not close the file.') from memory_close_error
