"""Four-role LangGraph orchestration with mandatory mem0 agent handoffs."""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict
from uuid import uuid4
from langgraph.graph import END, START, StateGraph
from utils.config import ResearchError
from comparison_app.observability import message
from comparison_app.models import Briefing, Claim, Discovery, Profile, Source, Synthesis, utc_now, validate_citations
from utils import common
log = common.initialize_logging(__file__)

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

    compile_instructions="""
    Compile an executive competitor-analysis briefing:
        Summarize the subject versus the three competitors.
        Identify supported opportunities and risks, and list limitations.
        Distinguish inference from fact.
        Do not introduce unsupported financials, rankings or product claims.
        """

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
        log.info('Step orchestrator_plan: validating company input and assigning run ID.')
        company = state['company'].strip()
        if not company or len(company) > 180:
            raise ResearchError('Enter a company name (up to 180 characters); adding its website can resolve ambiguity.')
        run_id = state.get('run_id') or uuid4().hex
        log.info('Run %s: planning complete; next step is competitor discovery.', run_id)
        message('orchestrator', 'agents', f'Run {run_id}: discover competitors, research profiles in parallel, then compile.', {'company': company})
        return {'company': company, 'run_id': run_id}

    def discover(self, state: ResearchState) -> dict:
        """Agent 1 discovers exactly three competitors through Tavily and saves to mem0."""
        log.info('Run %s: starting step agent_1_discovery; searching competitor evidence.', state['run_id'])
        company = state['company']
        evidence = self.search.search(f'{company} company top direct competitors alternatives market comparison')
        if not evidence:
            log.warning('Run %s: discovery stopped because no usable evidence was found.', state['run_id'])
            raise ResearchError('No competitor evidence found. Try a more specific company name or website.')
        log.info('Run %s: extracting competitor discovery from %d sources.', state['run_id'], len(evidence))
        discovery = self.analyst.extract(Discovery,
            'Resolve the subject company and identify its top 3 direct competitors based on relevance and evidence. '
            'Do not claim a measured market-share ranking. Specify the market/industry scope and justify each selection.',
            evidence, {'company_input': company})
        log.info('Run %s: validating discovery citations.', state['run_id'])
        validate_citations(discovery, evidence)
        message('agent 1', 'agents 2 and 3 via mem0', 'Competitor discovery completed.', discovery.model_dump())
        log.info('Run %s: saving discovery to mem0 before parallel research.', state['run_id'])
        self.memory.write(company, state['run_id'], 'discovery',
                          {'artifact': discovery.model_dump(), 'sources': [row.model_dump() for row in evidence]})
        return {}

    def profile(self, name: str, run_id: str = '-') -> tuple[Profile, list[Source], list[str]]:
        """Gather fresh pricing/features/news evidence and extract a comparable profile."""
        evidence, warnings = [], []

        queries = [(f'{name} official pricing plans cost per user billing', 'general'),
                   (f'{name} official product core features target customers market positioning', 'general'),
                   (f'{name} company product funding partnerships news', 'news')]

        for index, (query, topic) in enumerate(queries, start=1):
            try:
                log.info('Run %s: profile search %d/3 (%s) starting.', run_id, index,
                         ('pricing', 'features and positioning', 'recent news')[index - 1])
                results = self.search.search(query, topic)
                log.info('Run %s: profile search %d/3 returned %d sources.', run_id, index, len(results))
                evidence.extend(results)
                if not results:
                    log.warning('Run %s: profile search %d/3 returned no usable evidence.', run_id, index)
                    warnings.append(f'{name}: no usable {topic} evidence for one search.')
            except ResearchError:
                log.warning('Run %s: profile search %d/3 failed; continuing with partial research.', run_id, index)
                warnings.append(f'{name}: a {topic} search failed; research is partial.')
        log.info('Run %s: deduplicating profile evidence.', run_id)
        evidence = unique_sources(evidence)
        if not evidence:
            log.warning('Run %s: no profile evidence; returning an unverified profile.', run_id)
            return unknown_profile(name, 'All web/news searches failed or returned no usable evidence.'), [], warnings
        try:
            log.info('Run %s: extracting profile from %d sources.', run_id, len(evidence))
            profile = self.analyst.extract(Profile,
                f'Extract pricing, core features, market positioning, and news for {name}. '
                f'Only use dated news evidence from the last {self.news_days} days for recent news. '
                'If current official pricing cannot be verified, say so. Do not turn search failure into a negative fact.',
                evidence, {'company': name, 'today_utc': utc_now()})
            log.info('Run %s: validating profile company, citations and news sources.', run_id)
            if profile.company.strip().casefold() != name.strip().casefold():
                raise ResearchError('The profile returned a different company.')
            validate_citations(profile, evidence)
            news_ids = {source.id for source in evidence if source.topic == 'news'}
            for claim in profile.news:
                if claim.kind != 'unknown' and not set(claim.source_ids) <= news_ids:
                    raise ResearchError('Recent news must cite date-filtered news evidence.')
            return profile, evidence, warnings
        except ResearchError:
            log.warning('Run %s: profile extraction or validation failed; returning unverified claims.', run_id)
            warnings.append(f'{name}: profile extraction failed validation; claims are marked unverified.')
            return unknown_profile(name, 'Structured extraction or citation validation failed.'), evidence, warnings

    def research_competitors(self, state: ResearchState) -> dict:
        """Agent 2 queries mem0 for the competitor list and researches each company."""
        log.info('Run %s: starting step agent_2_competitors; reading discovery from mem0.', state['run_id'])
        saved = self.memory.read(state['company'], state['run_id'], 'discovery')
        discovery = Discovery.model_validate(saved['artifact'])
        message('mem0', 'agent 2', 'Retrieved competitor discovery.', discovery.model_dump())
        warnings = []
        for index, competitor in enumerate(discovery.competitors):
            log.info('Run %s: starting competitor profile %d/%d.', state['run_id'], index + 1, len(discovery.competitors))
            profile, sources, notes = self.profile(competitor.name, run_id=state['run_id'])
            message('agent 2', 'orchestrator via mem0', f'Competitor {index + 1} researched.', profile.model_dump())
            log.info('Run %s: saving competitor_%d profile to mem0.', state['run_id'], index)
            self.memory.write(state['company'], state['run_id'], f'competitor_{index}',
                {'artifact': profile.model_dump(), 'sources': [source.model_dump() for source in sources]})
            warnings.extend(notes)
        return {'warnings': warnings}

    def research_company(self, state: ResearchState) -> dict:
        """Agent 3 extracts pricing, features, positioning and news for the subject."""
        log.info('Run %s: starting step agent_3_company; reading discovery from mem0.', state['run_id'])
        saved = self.memory.read(state['company'], state['run_id'], 'discovery')
        name = Discovery.model_validate(saved['artifact']).company
        log.info('Run %s: starting subject-company profile research.', state['run_id'])
        profile, sources, warnings = self.profile(name, run_id=state['run_id'])
        message('agent 3', 'orchestrator via mem0', 'Subject company researched.', profile.model_dump())
        log.info('Run %s: saving target profile to mem0.', state['run_id'])
        self.memory.write(state['company'], state['run_id'], 'target',
            {'artifact': profile.model_dump(), 'sources': [source.model_dump() for source in sources]})
        return {'warnings': warnings}

    def compile_briefing(self, state: ResearchState) -> dict:
        """Orchestrator retrieves all agent memories and compiles a structured briefing."""
        log.info('Run %s: starting step orchestrator_briefing; reading discovery from mem0.', state['run_id'])
        saved = self.memory.read(state['company'], state['run_id'], 'discovery')
        discovery = Discovery.model_validate(saved['artifact'])
        sources = [Source.model_validate(row) for row in saved['sources']]
        profiles = []
        for kind in ('target', 'competitor_0', 'competitor_1', 'competitor_2'):
            log.info('Run %s: reading %s profile from mem0.', state['run_id'], kind)
            saved_profile = self.memory.read(state['company'], state['run_id'], kind)
            profile = Profile.model_validate(saved_profile['artifact'])
            evidence = [Source.model_validate(row) for row in saved_profile['sources']]
            log.info('Run %s: validating %s profile citations.', state['run_id'], kind)
            validate_citations(profile, evidence)
            sources.extend(evidence)
            profiles.append(profile)
        log.info('Run %s: deduplicating briefing evidence.', state['run_id'])
        sources = unique_sources(sources)
        log.info('Run %s: extracting briefing synthesis from %d sources.', state['run_id'], len(sources))
        synthesis = self.analyst.extract(Synthesis,
            self.compile_instructions, sources,
            {'discovery': discovery.model_dump(), 'profiles': [profile.model_dump() for profile in profiles],
             'warnings': state.get('warnings', [])})
        log.info('Run %s: validating briefing synthesis citations.', state['run_id'])
        validate_citations(synthesis, sources)
        message('orchestrator', 'user', 'Evidence-based briefing compiled.', synthesis.model_dump())
        log.info('Run %s: assembling structured briefing.', state['run_id'])
        briefing = Briefing(run_id=state['run_id'], company=discovery.company, generated_at=utc_now(),
            market_scope=discovery.market_scope, target=profiles[0], competitors=profiles[1:], discovery=discovery,
            synthesis=synthesis, sources=sources, warnings=state.get('warnings', []))
        log.info('Run %s: saving completed briefing to mem0.', state['run_id'])
        self.memory.write(state['company'], state['run_id'], 'briefing', {'artifact': briefing.model_dump()})
        log.info('Run %s: briefing completed with %d sources and %d warnings.',
                 state['run_id'], len(sources), len(briefing.warnings))
        return {'briefing': briefing}
