"""Tavily evidence collection and schema-validated OpenAI extraction."""
from __future__ import annotations

import json
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel
from utils.config import ResearchError, Settings
from comparison_app.models import Source, usable_url, utc_now, validate_citations
from comparison_app.analyst_rules import AnalysisRules
from utils import common

T = TypeVar('T', bound=BaseModel)


class Analyst:
    """Use strict typed extraction with the existing OpenAI-compatible endpoint."""

    def __init__(self, settings: Settings, log=None):
        """Configure bounded API retries and keep keys outside prompts and logs."""
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_key, base_url=settings.base_url,
                             timeout=settings.timeout, max_retries=2)
        self.log = log
        common.observe_client(self.client)

    def extract(self, schema: type[T], task: str, evidence: list[Source], context: dict | None = None) -> T:
        """Parse structured outputs and reject unsupported source references."""
        payload = json.dumps({'task': task, 'context': context or {},
                              'evidence': [source.model_dump() for source in evidence]}, ensure_ascii=False)
        try:
            common.message(schema.__name__, 'LLM', task, {'system': AnalysisRules.main_objective, 'user': json.loads(payload)})
            response = self.client.chat.completions.parse(model=self.settings.model,
                messages=[{'role': 'system', 'content': AnalysisRules.main_objective}, {'role': 'user', 'content': payload}],
                response_format=schema, max_completion_tokens=self.settings.max_output, store=False)
            result = response.choices[0].message.parsed
            if result is None:
                raise ResearchError('The model declined or did not return the requested structured research.')
            validate_citations(result, evidence)
            common.message('LLM', schema.__name__, 'Validated structured research response.', result.model_dump())
            self.log.info('Validated %s structured output.', schema.__name__)
            return result
        except ResearchError:
            raise
        except Exception as model_error:
            self.log.info(f"ERROR: {model_error}")
            raise ResearchError(f"Model extraction failed. Check OPENAI_MODEL, endpoint schema support, quota, and credentials. {model_error}") from model_error

    def close(self) -> None:
        """Release the research-model HTTP connection pool after a completed run."""
        self.client.close()
