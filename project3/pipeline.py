"""Four-role LangGraph orchestration with mandatory mem0 agent handoffs."""
from __future__ import annotations

import logging
import operator
from typing import Annotated, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from project3.config import ResearchError
from project3.models import Briefing, Claim, Discovery, Profile, Source, Synthesis, utc_now, validate_citations

log = logging.getLogger(__name__)


class ResearchState(TypedDict, total=False):
    """The graph carries control data; research artifacts are exchanged through mem0."""

    company: str
    run_id: str
    warnings: Annotated[list[str], operator.add]
    briefing: Briefing


def unknown_profile(company: str, reason: str) -> Profile:
    """Keep failed or missing research explicit instead of manufacturing facts."""
    unknown = Claim(text='Not verified in the available evidence.', source_ids=[], kind='unknown')
    return Profile(company=company, pricing=[unknown], features=[unknown], positioning=[unknown],
                   news=[unknown], gaps=[reason])


def unique_sources(sources: list[Source]) -> list[Source]:
    """Deduplicate repeated web links by stable source ID."""
    return list({source.id: source for source in sources}.values())


class ResearchPipeline:
    """Coordinate discovery, parallel research and source-grounded compilation."""

    def __init__(self, search, analyst, memory, news_days: int = 30):
        """Inject services so the exact live graph is testable without paid calls."""
        self.search, self.analyst, self.memory, self.news_days = search, analyst, memory, news_days
        graph = StateGraph(ResearchState)
        graph.add_node('orchestrator_plan', self.plan)
        graph.add_node('agent_1_discovery', self.discover)
        graph.add_node('agent_2_competitors', self.research_competitors)
        graph.add_node('agent_3_company', self.research_company)
        graph.add_node('orchestrator_briefing', self.compile_briefing)
        graph.add_edge(START, 'orchestrator_plan')
        graph.add_edge('orchestrator_plan', 'agent_1_discovery')
        graph.add_edge('agent_1_discovery', 'agent_2_competitors')
        graph.add_edge('agent_1_discovery', 'agent_3_company')
        graph.add_edge(['agent_2_competitors', 'agent_3_company'], 'orchestrator_briefing')
        graph.add_edge('orchestrator_briefing', END)
        self.graph = graph.compile()

    def plan(self, state: ResearchState) -> dict:
        """Validate user input and assign a fresh run before any search or memory access."""
        company = state['company'].strip()
        if not company or len(company) > 180:
            raise ResearchError('Enter a company name (up to 180 characters); adding its website can resolve ambiguity.')
        log.info('Orchestrator started research run.')
        return {'company': company, 'run_id': state.get('run_id') or uuid4().hex}

    def discover(self, state: ResearchState) -> dict:
        """Agent 1 discovers exactly three competitors through Tavily and saves to mem0."""
        log.info('Agent 1: discovering competitors.')
        company = state['company']
        evidence = self.search.search(f'{company} company top direct competitors alternatives market comparison')
        if not evidence:
            raise ResearchError('No competitor evidence found. Try a more specific company name or website.')
        discovery = self.analyst.extract(Discovery,
            'Resolve the subject company and identify its top 3 direct competitors based on relevance and evidence. '
            'Do not claim a measured market-share ranking. Specify the market/industry scope and justify each selection.',
            evidence, {'company_input': company})
        validate_citations(discovery, evidence)
        self.memory.write(company, state['run_id'], 'discovery',
                          {'artifact': discovery.model_dump(), 'sources': [row.model_dump() for row in evidence]})
        return {}

    def profile(self, name: str) -> tuple[Profile, list[Source], list[str]]:
        """Gather fresh pricing/features/news evidence and extract a comparable profile."""
        evidence, warnings = [], []
        queries = [(f'{name} official pricing plans cost per user billing', 'general'),
                   (f'{name} official product core features target customers market positioning', 'general'),
                   (f'{name} company product funding partnerships news', 'news')]
        for query, topic in queries:
            try:
                results = self.search.search(query, topic)
                evidence.extend(results)
                if not results:
                    warnings.append(f'{name}: no usable {topic} evidence for one search.')
            except ResearchError:
                warnings.append(f'{name}: a {topic} search failed; research is partial.')
        evidence = unique_sources(evidence)
        if not evidence:
            return unknown_profile(name, 'All web/news searches failed or returned no usable evidence.'), [], warnings
        try:
            profile = self.analyst.extract(Profile,
                f'Extract pricing, core features, market positioning, and news for {name}. '
                f'Only use dated news evidence from the last {self.news_days} days for recent news. '
                'If current official pricing cannot be verified, say so. Do not turn search failure into a negative fact.',
                evidence, {'company': name, 'today_utc': utc_now()})
            if profile.company.strip().casefold() != name.strip().casefold():
                raise ResearchError('The profile returned a different company.')
            validate_citations(profile, evidence)
            news_ids = {source.id for source in evidence if source.topic == 'news'}
            for claim in profile.news:
                if claim.kind != 'unknown' and not set(claim.source_ids) <= news_ids:
                    raise ResearchError('Recent news must cite date-filtered news evidence.')
            return profile, evidence, warnings
        except ResearchError:
            warnings.append(f'{name}: profile extraction failed validation; claims are marked unverified.')
            return unknown_profile(name, 'Structured extraction or citation validation failed.'), evidence, warnings

    def research_competitors(self, state: ResearchState) -> dict:
        """Agent 2 queries mem0 for the competitor list and researches each company."""
        log.info('Agent 2: retrieving competitors from mem0 and researching fresh evidence.')
        saved = self.memory.read(state['company'], state['run_id'], 'discovery')
        discovery = Discovery.model_validate(saved['artifact'])
        warnings = []
        for index, competitor in enumerate(discovery.competitors):
            profile, sources, notes = self.profile(competitor.name)
            self.memory.write(state['company'], state['run_id'], f'competitor_{index}',
                {'artifact': profile.model_dump(), 'sources': [source.model_dump() for source in sources]})
            warnings.extend(notes)
        return {'warnings': warnings}

    def research_company(self, state: ResearchState) -> dict:
        """Agent 3 extracts pricing, features, positioning and news for the subject."""
        log.info('Agent 3: extracting subject-company profile.')
        saved = self.memory.read(state['company'], state['run_id'], 'discovery')
        name = Discovery.model_validate(saved['artifact']).company
        profile, sources, warnings = self.profile(name)
        self.memory.write(state['company'], state['run_id'], 'target',
            {'artifact': profile.model_dump(), 'sources': [source.model_dump() for source in sources]})
        return {'warnings': warnings}

    def compile_briefing(self, state: ResearchState) -> dict:
        """Orchestrator retrieves all agent memories and compiles a structured briefing."""
        log.info('Orchestrator: retrieving shared research and compiling briefing.')
        saved = self.memory.read(state['company'], state['run_id'], 'discovery')
        discovery = Discovery.model_validate(saved['artifact'])
        sources = [Source.model_validate(row) for row in saved['sources']]
        profiles = []
        for kind in ('target', 'competitor_0', 'competitor_1', 'competitor_2'):
            saved_profile = self.memory.read(state['company'], state['run_id'], kind)
            profile = Profile.model_validate(saved_profile['artifact'])
            evidence = [Source.model_validate(row) for row in saved_profile['sources']]
            validate_citations(profile, evidence)
            sources.extend(evidence)
            profiles.append(profile)
        sources = unique_sources(sources)
        synthesis = self.analyst.extract(Synthesis,
            'Compile an executive competitor-analysis briefing: summarize the subject versus the three competitors, '
            'identify supported opportunities and risks, and list limitations. Distinguish inference from fact; '
            'do not introduce unsupported financials, rankings or product claims.', sources,
            {'discovery': discovery.model_dump(), 'profiles': [profile.model_dump() for profile in profiles],
             'warnings': state.get('warnings', [])})
        validate_citations(synthesis, sources)
        briefing = Briefing(run_id=state['run_id'], company=discovery.company, generated_at=utc_now(),
            market_scope=discovery.market_scope, target=profiles[0], competitors=profiles[1:], discovery=discovery,
            synthesis=synthesis, sources=sources, warnings=state.get('warnings', []))
        self.memory.write(state['company'], state['run_id'], 'briefing', {'artifact': briefing.model_dump()})
        log.info('Briefing completed with %d sources and %d warnings.', len(sources), len(briefing.warnings))
        return {'briefing': briefing}
