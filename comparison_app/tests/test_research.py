"""Offline tests run the real LangGraph with explicit service doubles."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from utils.config import ResearchError, Settings
from comparison_app.demo import DemoAnalyst, DemoMemory, DemoSearch
from comparison_app.export import filename, markdown_briefing, pdf_briefing
from comparison_app.memory_mem0 import SharedMemoryMem0
from comparison_app.models import Claim, Discovery, Source, validate_citations
from comparison_app.pipeline import ResearchPipeline
from comparison_app.services import SearchService


def settings() -> Settings:
    """Use fake credentials for offline service-contract tests."""
    return Settings('test', 'test-model', 'https://example.com/v1', 'test-mem0',
                    'test', 3, 30, 10, 500, 1500, 'test-workspace')


def demo_briefing():
    """Run the exact graph with fictional providers for export and UI fixtures."""
    return ResearchPipeline(DemoSearch(), DemoAnalyst(), DemoMemory()).graph.invoke(
        {'company': 'Northstar CRM (fictional)', 'warnings': []})['briefing'].model_copy(update={'demo': True})


class PipelineTests(unittest.TestCase):
    """Ensure all agent communication crosses the shared-memory contract."""

    def test_handoffs_and_three_competitors(self):
        """Agent 2 reads persisted discovery and the orchestrator reads each profile."""
        memory = DemoMemory()
        result = ResearchPipeline(DemoSearch(), DemoAnalyst(), memory).graph.invoke(
            {'company': 'Northstar CRM (fictional)', 'warnings': []})
        briefing = result['briefing']
        self.assertEqual(len(briefing.competitors), 3)
        self.assertLess(memory.events.index(('write', 'discovery')), memory.events.index(('read', 'discovery')))
        for kind in ('target', 'competitor_0', 'competitor_1', 'competitor_2'):
            self.assertIn(('read', kind), memory.events)
        self.assertIn(('write', 'briefing'), memory.events)
        self.assertNotIn('competitors', result)
        validate_citations(briefing, briefing.sources)

    def test_run_and_company_isolation(self):
        """An artifact from another company or run cannot satisfy a handoff."""
        memory = DemoMemory()
        memory.write('A', 'run1', 'discovery', {'value': 1})
        for company, run in [('B', 'run1'), ('A', 'run2')]:
            with self.assertRaises(KeyError):
                memory.read(company, run, 'discovery')

    def test_memory_failure_stops_pipeline(self):
        """Do not secretly fall back to passing state when mem0 is unavailable."""
        memory = DemoMemory()
        memory.write = MagicMock(side_effect=ResearchError('memory unavailable'))
        with self.assertRaises(ResearchError):
            ResearchPipeline(DemoSearch(), DemoAnalyst(), memory).graph.invoke({'company': 'Example'})
        self.assertEqual(memory.events, [])

    def test_blank_input_rejected(self):
        """Reject blank company names before calling Tavily or mem0."""
        search = MagicMock()
        with self.assertRaises(ResearchError):
            ResearchPipeline(search, DemoAnalyst(), DemoMemory()).graph.invoke({'company': ' '})
        search.search.assert_not_called()

    def test_failed_profile_search_is_unknown(self):
        """Unavailable evidence becomes an explicit gap, never a product assertion."""
        search = MagicMock()
        search.search.side_effect = ResearchError('unavailable')
        profile, sources, warnings = ResearchPipeline(search, DemoAnalyst(), DemoMemory()).profile('Company')
        self.assertEqual(profile.pricing[0].kind, 'unknown')
        self.assertEqual(sources, [])
        self.assertEqual(len(warnings), 3)

    def test_discovery_and_citation_guards(self):
        """Reject duplicate competitors and unsupported citation IDs."""
        discovery = demo_briefing().discovery.model_dump()
        discovery['competitors'][1] = discovery['competitors'][0]
        with self.assertRaises(ValidationError):
            Discovery.model_validate(discovery)
        with self.assertRaises(ValidationError):
            Claim(text='Unsupported assertion', source_ids=[], kind='fact')
        with self.assertRaises(ResearchError):
            validate_citations(Claim(text='Wrong source', source_ids=['invented'], kind='fact'), [])


class SearchTests(unittest.TestCase):
    """Validate Tavily request parameters and news freshness at the API boundary."""

    def test_news_dates_and_non_http_links(self):
        """Keep recent ISO/RFC dates and drop old, undated or unsafe news URLs."""
        client = SearchService(settings())
        now = datetime.now(timezone.utc)
        values = [now.isoformat(), now.strftime('%a, %d %b %Y %H:%M:%S GMT'),
                  (now - timedelta(days=60)).isoformat(), '']
        client.client.search = MagicMock(return_value={'results': [
            {'url': f'https://example.com/{index}', 'title': 'News', 'content': 'Body', 'published_date': value}
            for index, value in enumerate(values)] + [{'url': 'javascript:alert(1)', 'published_date': now.isoformat()}]})
        result = client.search('Company news', topic='news')
        self.assertEqual(len(result), 2)
        self.assertEqual(client.client.search.call_args.kwargs['days'], 30)
        self.assertFalse(client.client.search.call_args.kwargs['include_answer'])

    def test_empty_search_and_retry_budget(self):
        """Do not manufacture search results and stop after bounded retries."""
        client = SearchService(settings())
        client.client.search = MagicMock(return_value={'results': []})
        self.assertEqual(client.search('Company'), [])
        client.client.search.side_effect = RuntimeError('private-secret-not-for-logs')
        with patch('comparison_app.services.time.sleep'), self.assertRaises(ResearchError) as caught:
            client.search('Company')
        self.assertNotIn('private-secret', str(caught.exception))
        self.assertEqual(client.client.search.call_count, 4)


class MemoryContractTests(unittest.TestCase):
    """Check exact mem0 artifacts, filters and SDK-version-specific contracts."""

    def test_run_scoped_search_and_exact_artifact(self):
        """Filters must include run, company namespace and artifact kind."""
        memory = SharedMemoryMem0.__new__(SharedMemoryMem0)
        from threading import RLock
        memory.lock, memory.workspace, memory.client = RLock(), 'workspace', MagicMock()
        payload = {'competitors': ['A', 'B', 'C']}
        memory.client.add.return_value = {'results': [{'id': 'id'}]}
        memory.write('Acme', 'run-one', 'discovery', payload)
        call = memory.client.add.call_args
        self.assertFalse(call.kwargs['infer'])
        self.assertEqual(json.loads(call.kwargs['metadata']['artifact_json']), payload)
        memory.client.search.return_value = {'results': [{'metadata': {'kind': 'discovery', 'artifact_json': json.dumps(payload)}}]}
        self.assertEqual(memory.read('Acme', 'run-one', 'discovery'), payload)
        filters = memory.client.search.call_args.kwargs['filters']
        self.assertEqual(filters['run_id'], 'run-one')
        self.assertEqual(filters['kind'], 'discovery')
        self.assertNotEqual(memory.namespace('Acme'), memory.namespace('Other'))


class ExportTests(unittest.TestCase):
    """Verify searchable PDF text, escaping and source-register completeness."""

    def test_pdf_and_markdown_include_all_companies(self):
        """PDF export keeps every profile and its source references readable."""
        briefing = demo_briefing()
        data = pdf_briefing(briefing)
        self.assertTrue(data.startswith(b'%PDF'))
        reader = PdfReader(BytesIO(data))
        text = '\n'.join(page.extract_text() for page in reader.pages)
        for profile in [briefing.target, *briefing.competitors]:
            self.assertIn(profile.company, text)
        self.assertIn('SYNTHETIC DEMO', text)
        self.assertIn('Source register', text)
        self.assertIn('example.com', text)
        self.assertIn('Market scope', markdown_briefing(briefing))
        self.assertNotIn('/', filename('../../Untrusted / Company'))

    def test_pdf_escapes_markup(self):
        """Source titles and generated prose cannot inject ReportLab markup."""
        briefing = demo_briefing()
        briefing.target.features[0].text = 'Literal <b> markup & price > comparison'
        data = pdf_briefing(briefing)
        text = ''.join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)
        self.assertIn('Literal <b> markup', text)


class InterfaceTests(unittest.TestCase):
    """Exercise the Streamlit workflow without external services or real credentials."""

    def test_demo_and_pdf_download(self):
        """A submitted fictional company produces a report and PDF download."""
        app_path = Path(__file__).resolve().parents[1] / 'app.py'
        with patch('comparison_app.app.configure_logging'):
            app = AppTest.from_file(str(app_path), default_timeout=30).run()
            app.sidebar.radio[0].set_value('Offline demo').run()
            next(button for button in app.button if button.label == 'Build competitor briefing').click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.metric[0].value, '3')
        self.assertIn('p3_pdf', app.session_state)
        self.assertTrue(app.session_state['p3_pdf'].startswith(b'%PDF'))

    def test_theme_switch_preserves_briefing(self):
        """Changing appearance must retain the report and PDF without new research."""
        app_path = Path(__file__).resolve().parents[1] / 'app.py'
        with patch.dict(os.environ, {'P3_DEFAULT_THEME': 'light'}):
            app = AppTest.from_file(str(app_path), default_timeout=30).run()
            app.sidebar.radio[0].set_value('Offline demo').run()
            next(button for button in app.button if button.label == 'Build competitor briefing').click().run()
            run_id = app.session_state['p3_briefing'].run_id
            pdf = app.session_state['p3_pdf']
            app.sidebar.toggle[0].set_value(True).run()
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertTrue(app.session_state['p3_dark_theme'])
            self.assertEqual(app.query_params['appearance'], 'dark')
            self.assertEqual(app.session_state['p3_briefing'].run_id, run_id)
            self.assertEqual(app.session_state['p3_pdf'], pdf)
            app.sidebar.toggle[0].set_value(False).run()
            self.assertFalse(app.exception)
            self.assertFalse(app.session_state['p3_dark_theme'])
            self.assertEqual(app.session_state['p3_briefing'].run_id, run_id)
            other = AppTest.from_file(str(app_path), default_timeout=30).run()
            self.assertFalse(other.session_state['p3_dark_theme'])
