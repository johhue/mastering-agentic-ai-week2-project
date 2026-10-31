"""Tavily evidence collection and schema-validated OpenAI extraction."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import time
from typing import TypeVar

from pydantic import BaseModel
from tavily import TavilyClient
from utils.config import ResearchError, Settings
from comparison_app.models import Source, usable_url, utc_now, validate_citations
from utils import common

T = TypeVar('T', bound=BaseModel)

class SearchServiceWikipedia:
    """Collect fresh, bounded search excerpts from Tavily, without persistent caching."""

    def __init__(self, log=None, config_dict=None, settings: Settings = None):
        """Configure the primary search source with an explicit request timeout."""

        self.log = log
        self.config_dict = config_dict
        self.settings = settings
        self.search_client = TavilyClient(api_key=settings.tavily_key)

    def search(self, query: str, topic: str = 'general') -> list[Source]:
        """Retry Tavily reads, preserve dates, and omit invalid or undated news links."""

        options = {'topic': topic, 'max_results': self.settings.results, 'include_answer': False,
                   'include_raw_content': False, 'search_depth': 'advanced',
                   'timeout': self.settings.timeout}
        if topic == 'news':
            options['days'] = self.settings.news_days
        for attempt in range(3):
            try:
                self.log.info('External Tavily POST url=%s attempt=%d topic=%s',
                         common.safe_url(str(self.search_client.base_url).rstrip('/') + '/search'), attempt + 1, topic)
                common.message('research agent', 'Tavily', 'Searching for fresh evidence.', {'query': query, 'topic': topic})
                response = self.client.search(query=query, **options)
                evidence = []

                for row in response.get('results', []):
                    if not usable_url(row.get('url', '')):
                        continue
                    published = row.get('published_date') or ''
                    if topic == 'news':
                        try:
                            try:
                                date = datetime.fromisoformat(published.replace('Z', '+00:00'))
                            except ValueError:
                                date = parsedate_to_datetime(published)
                            if date.tzinfo is None:
                                date = date.replace(tzinfo=timezone.utc)
                            now = datetime.now(timezone.utc)
                            if date < now - timedelta(days=self.settings.news_days) or date > now + timedelta(days=1):
                                continue
                        except (ValueError, TypeError):
                            continue

                    evidence.append(Source(id='S' + hashlib.sha256(row['url'].encode()).hexdigest()[:12],
                        title=row.get('title') or row['url'], url=row['url'],
                        content=(row.get('content') or '')[:10000],
                        published_at=published, retrieved_at=utc_now(), topic=topic))

                self.log.info('Tavily %s search returned %d usable sources.', topic, len(evidence))
                for source in evidence:
                    self.log.info('Search evidence source=%s url=%s (returned by Tavily; not fetched directly)',
                             source.id, common.safe_url(source.url))
                return evidence
            except Exception as search_error:
                if attempt == 2:
                    raise ResearchError('Tavily search failed. Check TAVILY_API_KEY, quota, and connectivity.') from search_error
                self.log.warning('Tavily request failed (%s) error=%s; retrying.', type(search_error).__name__, search_error)
                time.sleep(2 ** attempt)
        raise ResearchError('Tavily retry budget exhausted.')
