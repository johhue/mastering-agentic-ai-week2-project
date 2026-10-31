"""Streamlit multi-agent market research with a downloadable competitor briefing."""
from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from utils.config import ResearchError, Settings, load_environment
from comparison_app.demo import DemoAnalyst, DemoMemory, DemoSearch
from comparison_app.export import citation_numbers, claim_text, filename, markdown_briefing, pdf_briefing
from comparison_app.memory_mem0 import SharedMemoryMem0
from comparison_app.memory_filesystem import SharedMemoryFileSystem
from comparison_app.pipeline import ResearchPipeline
from comparison_app.search_service import TavilySearchService
from comparison_app.analyst_service import Analyst
from comparison_app.appearance import render_appearance
from comparison_app.analyst_rules import AnalysisRules

from utils import common

log = common.initialize_logging(__file__)

def clear_chat_history() -> None:
    """Clear this session's research history and downloads while retaining preferences."""
    log.info('Clearing session research history and downloads.')
    for key in ('p3_briefing', 'p3_pdf', 'p3_company', 'p3_demo_company', 'messages', 'chat_history'):
        st.session_state.pop(key, None)
    log.info('User cleared the current session chat and research history.')


def research(company: str, demo: bool) -> None:
    """Execute the real graph, streaming completed agent stages into the interface."""
    memory = None
    analyst = None
    try:
        log.info('Preparing research services (demo=%s).', demo)
        if demo:
            log.info('Initializing offline memory and research pipeline.')
            memory = DemoMemory()
            pipeline = ResearchPipeline(DemoSearch(), DemoAnalyst(), memory)
        else:
            log.info('Loading and validating live research settings from .env.')
            settings = Settings.from_env()

            memory = None

            log.info('Selecting the configured research memory backend.')
            if 'MEMORY_METHOD' in os.environ:
                if os.environ['MEMORY_METHOD'] == "MEM0":
                    log.info('Initializing hosted mem0 memory.')
                    memory = SharedMemoryMem0(settings)
                elif os.environ['MEMORY_METHOD'] == "FILESYSTEM":
                    log.info('Initializing filesystem memory.')
                    memory = SharedMemoryFileSystem(settings)
                else:
                    raise Exception(f"MEMORY_METHOD is set, but not to a valid option: {os.environ['MEMORY_METHOD']}")
            else:
                raise Exception('MEMORY_METHOD environment variable not set, check .env file.')

            log.info('Initializing the research analyst client.')
            analyst = Analyst(settings)
            log.info('Initializing Tavily search and the research pipeline.')
            pipeline = ResearchPipeline(TavilySearchService(settings), analyst, memory, settings.news_days)
        log.info('Opening research progress display and starting the graph stream.')
        with st.status('Researching the competitive landscape…', expanded=True) as progress:
            for update in pipeline.graph.stream({'company': company, 'warnings': []},
                                                config={'max_concurrency': 2}, stream_mode='updates'):
                for stage, state in update.items():
                    log.info('Displaying completed research stage: %s.', stage)
                    st.write(AnalysisRules.analysis_stages.get(stage, stage))
                    if state and state.get('briefing'):
                        log.info('Saving completed briefing to session state. Run ID: %s.', state['briefing'].run_id)
                        briefing = state['briefing'].model_copy(update={'demo': demo})
                        st.session_state['p3_briefing'] = briefing
            log.info('Marking research progress complete.')
            progress.update(label='Briefing ready', state='complete', expanded=False)
        try:
            log.info('Generating PDF for the session briefing.')
            st.session_state['p3_pdf'] = pdf_briefing(st.session_state['p3_briefing'])
            log.info('PDF saved to session state.')
        except ResearchError as export_error:
            log.error('PDF generation failed (%s).', type(export_error).__name__)
            st.warning(str(export_error))
    finally:
        if analyst:
            try:
                log.info('Closing the research analyst client.')
                analyst.close()
            except Exception as model_cleanup_error:
                log.warning('Model client cleanup failed (%s).', type(model_cleanup_error).__name__)
        if memory:
            try:
                log.info('Closing the research memory client.')
                memory.close()
            except Exception as cleanup_error:
                log.warning('Research client cleanup failed (%s).', type(cleanup_error).__name__)


def show_briefing() -> None:
    """Render the same structured findings that appear in the exported PDF."""
    briefing = st.session_state.get('p3_briefing')
    if not briefing:
        log.debug('Skipping briefing rendering: no session briefing is available.')
        return
    log.info('Run %s: preparing briefing references and summary.', briefing.run_id)
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
    log.info('Run %s: rendering the competitive landscape table.', briefing.run_id)
    st.subheader('Competitive landscape')
    st.table([{'Company': profile.company,
                   'Pricing': claim_text(profile.pricing[0], references),
                   'Core features': claim_text(profile.features[0], references),
                   'Positioning': claim_text(profile.positioning[0], references)}
                  for profile in [briefing.target, *briefing.competitors]])
    details, full, sources = st.tabs(['Company profiles', 'Full briefing', 'Sources & limitations'])
    with details:
        log.info('Run %s: rendering company profile details.', briefing.run_id)
        for index, profile in enumerate([briefing.target, *briefing.competitors], start=1):
            log.debug('Run %s: rendering profile %d.', briefing.run_id, index)
            with st.expander(profile.company, expanded=profile is briefing.target):
                for title, claims in [('Pricing', profile.pricing), ('Core features', profile.features),
                                      ('Market positioning', profile.positioning), ('Recent news', profile.news)]:
                    st.markdown(f'**{title}**')
                    for claim in claims:
                        st.write(claim_text(claim, references))
                for gap in profile.gaps:
                    st.caption('Gap: ' + gap)
    with full:
        log.info('Run %s: rendering the full Markdown briefing.', briefing.run_id)
        st.markdown(markdown_briefing(briefing))
    with sources:
        log.info('Run %s: rendering sources and research limitations.', briefing.run_id)
        for note in [*briefing.warnings, *briefing.synthesis.limitations]:
            st.warning(note)
        for source in briefing.sources:
            st.markdown(f'**[{references[source.id]}] {source.title}**')
            st.link_button('Open source', source.url)
            st.caption(f'Published: {source.published_at or "not supplied"} · Retrieved: {source.retrieved_at}')
        st.caption('A source reference establishes provenance, not independent verification. '
                   'Search excerpts can be incomplete; verify purchase decisions with the original sources.')
    st.divider()
    log.info('Run %s: preparing briefing download controls.', briefing.run_id)
    pdf = st.session_state.get('p3_pdf')
    if pdf:
        st.download_button('Download briefing as PDF', pdf, filename(briefing.company), 'application/pdf', type='primary')
    elif st.button('Prepare PDF download'):
        log.info('Run %s: regenerating PDF at user request.', briefing.run_id)
        st.session_state['p3_pdf'] = pdf_briefing(briefing)
        log.info('Run %s: rerunning the page to display the PDF download.', briefing.run_id)
        st.rerun()
    log.info('Run %s: serializing structured JSON for download.', briefing.run_id)
    st.download_button('Download structured JSON', briefing.model_dump_json(indent=2),
                       'competitor-briefing.json', 'application/json')


def main() -> None:
    """Prompt for a company and keep paid research behind an explicit submission."""
    log.info('Configuring the Streamlit research page.')
    st.set_page_config(page_title='Mastering Agentic AI Project 3A -- Market Research Agent', page_icon='🔎', layout='wide')
    try:

        log.info('Rendering page appearance and research mode controls.')
        render_appearance()
        st.title('Mastering Agentic AI Project 3A -- Market Research Agent')
        st.caption('A multi-agent briefing on your company and its competitive landscape')
        mode = st.sidebar.radio('Research mode', ['Live research', 'Offline demo'])
        demo = mode == 'Offline demo'
        log.info('Rendering research mode guidance (demo=%s).', demo)
        st.sidebar.markdown('**The research team**\n\n1. Discover competitors\n2. Research competitors\n3. Profile your company\n4. Compile the briefing')
        if demo:
            st.info('Offline preview using fictional companies. No Tavily, OpenAI or mem0 calls are made.')
        else:
            st.info('Live research uses Tavily, OpenAI and shared mem0 memory. A full run makes '
                    '13 search requests plus retries, along with model and embedding calls.')
            with st.sidebar.expander('Connection setup'):
                log.info('Loading environment for connection setup indicators.')
                load_environment()
                for key in ('TAVILY_API_KEY', 'OPENAI_API_KEY', 'MEM0_API_KEY'):
                    st.write(f'{key}: {"configured" if os.getenv(key) else "missing"}')
                st.caption('Credentials belong in the repository .env. Memory is stored in hosted mem0.ai.')
        log.info('Rendering the company research form.')
        with st.form('company_research'):
            company = st.text_input('Company or Product to Research', value='Northstar CRM (fictional)' if demo else '',
                                    placeholder='Company or Product Name (Add Website in Parentheses)', max_chars=180,
                                    disabled=demo, key='p3_demo_company' if demo else 'p3_company')
            submitted = st.form_submit_button('Build competitor briefing', type='primary')
        log.debug('Rendering the clear-history control.')
        st.sidebar.button('Clear chat history', key='p3_clear_history', on_click=clear_chat_history,
                          help='Clear this session’s company input, conversation and report downloads.')
        if submitted:
            log.info('Research form submitted; clearing previous briefing and PDF.')
            st.session_state.pop('p3_briefing', None)
            st.session_state.pop('p3_pdf', None)
            if not company.strip():
                log.warning('Research submission rejected: company input is blank.')
                st.warning('Enter a company name to begin.')
            else:
                log.info('Starting submitted research (demo=%s).', demo)
                research(company, demo)
        log.info('Checking for a session briefing to render.')
        show_briefing()
        log.debug('Streamlit page rendering complete.')
    except ResearchError as research_error:
        log.error('Research operation failed (%s). %s', type(research_error).__name__, research_error)
        log.error('Research error: %s', research_error)
        st.error(str(research_error))
    except Exception as unexpected_error:
        log.error('Unexpected research failure (%s) unexpected_error=%s.', type(unexpected_error).__name__, unexpected_error)
        st.error('Research could not complete. Check service access and the application logs. '
                 f'Error type: {type(unexpected_error).__name__}.')


if __name__ == '__main__':
    main()
