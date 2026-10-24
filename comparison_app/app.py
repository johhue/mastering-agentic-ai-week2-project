"""Streamlit multi-agent market research with a downloadable competitor briefing."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from utils.config import ResearchError, Settings, load_environment
from utils.common import configure_logging, get_required_env
from comparison_app.demo import DemoAnalyst, DemoMemory, DemoSearch
from comparison_app.export import citation_numbers, claim_text, filename, markdown_briefing, pdf_briefing
from comparison_app.memory_mem0 import SharedMemoryMem0
from comparison_app.memory_filesystem import SharedMemoryFileSystem
from comparison_app.pipeline import ResearchPipeline
from comparison_app.services import Analyst, SearchService
from comparison_app.appearance import render_appearance

log = configure_logging()

STAGES = {'orchestrator_plan': 'Orchestrator planned the research run',
          'agent_1_discovery': 'Agent 1 saved three competitors to shared memory',
          'agent_2_competitors': 'Agent 2 researched all three competitors',
          'agent_3_company': 'Agent 3 extracted the company profile',
          'orchestrator_briefing': 'Orchestrator compiled the competitor briefing'}


def clear_chat_history() -> None:
    """Clear this session's research history and downloads while retaining preferences."""
    for key in ('p3_briefing', 'p3_pdf', 'p3_company', 'p3_demo_company', 'messages', 'chat_history'):
        st.session_state.pop(key, None)
    log.info('User cleared the current session chat and research history.')


def research(company: str, demo: bool) -> None:
    """Execute the real graph, streaming completed agent stages into the interface."""
    memory = None
    analyst = None
    try:
        if demo:
            memory = DemoMemory()
            pipeline = ResearchPipeline(DemoSearch(), DemoAnalyst(), memory)
        else:
            settings = Settings.from_env()
            # memory = SharedMemoryMem0(settings)
            memory = SharedMemoryFileSystem(settings)
            analyst = Analyst(settings)
            pipeline = ResearchPipeline(SearchService(settings), analyst, memory, settings.news_days)
        with st.status('Researching the competitive landscape…', expanded=True) as progress:
            for update in pipeline.graph.stream({'company': company, 'warnings': []},
                                                config={'max_concurrency': 2}, stream_mode='updates'):
                for stage, state in update.items():
                    st.write(STAGES.get(stage, stage))
                    if state and state.get('briefing'):
                        briefing = state['briefing'].model_copy(update={'demo': demo})
                        st.session_state['p3_briefing'] = briefing
            progress.update(label='Briefing ready', state='complete', expanded=False)
        try:
            st.session_state['p3_pdf'] = pdf_briefing(st.session_state['p3_briefing'])
        except ResearchError as export_error:
            log.error('PDF generation failed (%s).', type(export_error).__name__)
            st.warning(str(export_error))
    finally:
        if analyst:
            try:
                analyst.close()
            except Exception as model_cleanup_error:
                log.warning('Model client cleanup failed (%s).', type(model_cleanup_error).__name__)
        if memory:
            try:
                memory.close()
            except Exception as cleanup_error:
                log.warning('Research client cleanup failed (%s).', type(cleanup_error).__name__)


def show_briefing() -> None:
    """Render the same structured findings that appear in the exported PDF."""
    briefing = st.session_state.get('p3_briefing')
    if not briefing:
        return
    references = citation_numbers(briefing)
    if briefing.demo:
        st.warning('SYNTHETIC DEMO: companies, pricing and findings below are fictional.')
    st.header(f'{briefing.company}: competitor briefing')
    st.caption(f'Researched {briefing.generated_at[:10]} UTC · {briefing.market_scope} · Run {briefing.run_id[:12]}')
    columns = st.columns(3)
    columns[0].metric('Competitors', len(briefing.competitors))
    columns[1].metric('Sources', len(briefing.sources))
    columns[2].metric('Collection notes', len(briefing.warnings))
    for claim in briefing.synthesis.executive_summary:
        st.markdown('- ' + claim_text(claim, references))
    st.subheader('Competitive landscape')
    st.table([{'Company': profile.company,
                   'Pricing': claim_text(profile.pricing[0], references),
                   'Core features': claim_text(profile.features[0], references),
                   'Positioning': claim_text(profile.positioning[0], references)}
                  for profile in [briefing.target, *briefing.competitors]])
    details, full, sources = st.tabs(['Company profiles', 'Full briefing', 'Sources & limitations'])
    with details:
        for profile in [briefing.target, *briefing.competitors]:
            with st.expander(profile.company, expanded=profile is briefing.target):
                for title, claims in [('Pricing', profile.pricing), ('Core features', profile.features),
                                      ('Market positioning', profile.positioning), ('Recent news', profile.news)]:
                    st.markdown(f'**{title}**')
                    for claim in claims:
                        st.write(claim_text(claim, references))
                for gap in profile.gaps:
                    st.caption('Gap: ' + gap)
    with full:
        st.markdown(markdown_briefing(briefing))
    with sources:
        for note in [*briefing.warnings, *briefing.synthesis.limitations]:
            st.warning(note)
        for source in briefing.sources:
            st.markdown(f'**[{references[source.id]}] {source.title}**')
            st.link_button('Open source', source.url)
            st.caption(f'Published: {source.published_at or "not supplied"} · Retrieved: {source.retrieved_at}')
        st.caption('A source reference establishes provenance, not independent verification. '
                   'Search excerpts can be incomplete; verify purchase decisions with the original sources.')
    st.divider()
    pdf = st.session_state.get('p3_pdf')
    if pdf:
        st.download_button('Download briefing as PDF', pdf, filename(briefing.company), 'application/pdf', type='primary')
    elif st.button('Prepare PDF download'):
        st.session_state['p3_pdf'] = pdf_briefing(briefing)
        st.rerun()
    st.download_button('Download structured JSON', briefing.model_dump_json(indent=2),
                       'competitor-briefing.json', 'application/json')


def main() -> None:
    """Prompt for a company and keep paid research behind an explicit submission."""
    log.info("Starting ...")
    st.set_page_config(page_title='Mastering Agentic AI Project 3A -- Market Research Agent', page_icon='🔎', layout='wide')
    try:
        log.info("Starting ...")
        render_appearance()
        st.title('Mastering Agentic AI Project 3A -- Market Research Agent')
        st.caption('A multi-agent briefing on your company and its competitive landscape')
        mode = st.sidebar.radio('Research mode', ['Live research', 'Offline demo'])
        demo = mode == 'Offline demo'
        st.sidebar.markdown('**The research team**\n\n1. Discover competitors\n2. Research competitors\n3. Profile your company\n4. Compile the briefing')
        if demo:
            st.info('Offline preview using fictional companies. No Tavily, OpenAI or mem0 calls are made.')
        else:
            st.info('Live research uses Tavily, OpenAI and shared mem0 memory. A full run makes '
                    '13 search requests plus retries, along with model and embedding calls.')
            with st.sidebar.expander('Connection setup'):
                load_environment()
                for key in ('TAVILY_API_KEY', 'OPENAI_API_KEY', 'MEM0_API_KEY'):
                    st.write(f'{key}: {"configured" if os.getenv(key) else "missing"}')
                st.caption('Credentials belong in the repository .env. Memory is stored in hosted mem0.ai.')
        with st.form('company_research'):
            company = st.text_input('Company or Product to Research', value='Northstar CRM (fictional)' if demo else '',
                                    placeholder='Company or Product Name (Add Website in Parentheses)', max_chars=180,
                                    disabled=demo, key='p3_demo_company' if demo else 'p3_company')
            submitted = st.form_submit_button('Build competitor briefing', type='primary')
        st.sidebar.button('Clear chat history', key='p3_clear_history', on_click=clear_chat_history,
                          help='Clear this session’s company input, conversation and report downloads.')
        if submitted:
            st.session_state.pop('p3_briefing', None)
            st.session_state.pop('p3_pdf', None)
            if not company.strip():
                st.warning('Enter a company name to begin.')
            else:
                research(company, demo)
        show_briefing()
    except ResearchError as research_error:
        log.error('Research operation failed (%s).', type(research_error).__name__)
        log.error('Research error: %s', research_error)
        st.error(str(research_error))
    except Exception as unexpected_error:
        log.error(f"Error: {unexpected_error}")
        log.error('Unexpected research failure (%s).', type(unexpected_error).__name__)
        st.error('Research could not complete. Check service access and the application logs. '
                 f'Error type: {type(unexpected_error).__name__}.')


if __name__ == '__main__':
    main()
