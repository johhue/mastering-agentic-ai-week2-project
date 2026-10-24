"""Explicitly fictional offline services to exercise the real research graph."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock

from comparison_app.models import Claim, Competitor, Discovery, Profile, Source, Synthesis, utc_now


class DemoMemory:
    """An isolated in-process test double; never claim this is persistent mem0."""

    def __init__(self):
        """Initialize a demo-only keyed store and observable read/write events."""
        self.records = {}
        self.events = []
        self.lock = RLock()

    def write(self, company, run_id, kind, payload):
        """Record the same handoff contract used by the live mem0 adapter."""
        with self.lock:
            self.records[(company, run_id, kind)] = deepcopy(payload)
            self.events.append(('write', kind))

    def read(self, company, run_id, kind):
        """Read only previously written artifacts from the exact demo run."""
        with self.lock:
            self.events.append(('read', kind))
            return deepcopy(self.records[(company, run_id, kind)])

    def close(self):
        """Release no external resources in offline mode."""


class DemoSearch:
    """Return fictional fixtures instead of accessing Tavily or real websites."""

    def search(self, query, topic='general'):
        """Provide clearly labeled example evidence and reserved example.com links."""
        return [Source(id='DEMO-NEWS' if topic == 'news' else 'DEMO-WEB',
            title='Fictional demonstration evidence', url=f'https://example.com/{topic}',
            content='SYNTHETIC: example plans, collaboration features and hypothetical launch news.',
            retrieved_at=utc_now(), published_at=utc_now() if topic == 'news' else '', topic=topic)]


class DemoAnalyst:
    """Return structured fictional artifacts to demonstrate each agent's role."""

    def extract(self, schema, task, evidence, context=None):
        """Use typed fixtures; never present these as live company research."""
        source = next((row.id for row in evidence if row.topic == 'general'), evidence[0].id)
        fact = Claim(text='Fictional demonstration evidence only.', source_ids=[source], kind='fact')
        if schema is Discovery:
            return Discovery(company='Northstar CRM (fictional)', market_scope='Fictional CRM collaboration software',
                competitors=[Competitor(name=name, rationale=fact) for name in
                             ('Orbit CRM (fictional)', 'Harbor CRM (fictional)', 'Summit CRM (fictional)')])
        if schema is Profile:
            news = next((row.id for row in evidence if row.topic == 'news'), source)
            name = context['company']
            price = {'Northstar CRM (fictional)': 'USD 29', 'Orbit CRM (fictional)': 'USD 19',
                     'Harbor CRM (fictional)': 'USD 49'}.get(name)
            pricing = f'Example: {price} per user/month, billed annually. Synthetic pricing.' if price else 'Example: custom enterprise quotes; public pricing not supplied. Synthetic pricing.'
            return Profile(company=context['company'],
                pricing=[Claim(text=pricing, source_ids=[source], kind='fact')],
                features=[Claim(text='Example: shared pipelines, workflow automation, dashboards and team collaboration.', source_ids=[source], kind='fact')],
                positioning=[Claim(text='Example positioning: growing service teams seeking simple CRM workflows.', source_ids=[source], kind='fact')],
                news=[Claim(text='Synthetic recent-news example: a collaboration release was announced.', source_ids=[news], kind='fact')],
                gaps=['All figures and claims in this demo are fictional.'])
        return Synthesis(executive_summary=[fact], opportunities=[Claim(
            text='Illustrative inference: simpler onboarding could differentiate a CRM offering.', source_ids=[source], kind='inference')],
            risks=[Claim(text='Illustrative inference: similar features may increase price pressure.', source_ids=[source], kind='inference')],
            limitations=['Offline demonstration; no actual company, Tavily, OpenAI or mem0 service was queried.'])
