"""Offline contracts for evidence, integrations, persistent memory and synthesis."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import MagicMock, patch

import httpx
from project2.status_agent.core import Item, Snapshot, analyze, demo_history, report_markdown
from project2.status_agent.connectors import Collector, SourceError, collect, notion_value, scope_id
from project2.status_agent.agent import evidence_answer, weekly_report
from project2.status_agent.memory import Memory


class EvidenceTests(unittest.TestCase):
    """Test observed aging and risk semantics without inferring absent facts."""

    def test_carryover_and_weekly_done(self):
        """Demo must show aged work, explicit blockers and one completion transition."""
        analysis = analyze(demo_history())
        payment = next(row for row in analysis['risks'] if row['source'] == 'jira')
        self.assertEqual(payment['unchanged_days'], 21)
        self.assertEqual(len(payment['sprint_labels']), 2)
        self.assertEqual(analysis['sprints'][0]['blocked'], 1)
        self.assertEqual(analysis['trends'][0]['newly_done_observed'], ['asana:DEMO-28'])
        self.assertIn('RED', report_markdown(analysis))

    def test_failed_coverage_and_disappearance_break_continuity(self):
        """Failed or missing observations cannot manufacture long-standing stalls."""
        history = demo_history()
        history[1].coverage['jira'] = 'failed'
        history[1].items = [item for item in history[1].items if item.source != 'notion']
        analysis = analyze(history)
        self.assertTrue(all(row['unchanged_days'] == 0 for row in analysis['risks']))
        self.assertFalse(any(row['source'] == 'jira' for row in analysis['trends']))

    def test_status_change_done_and_threshold(self):
        """Changed or done status resets aging; exactly one sprint is not more than one."""
        history = demo_history()
        history[0].items[0] = replace(history[0].items[0], status='Ready')
        self.assertEqual(analyze(history)['risks'][0]['unchanged_days'], 14)
        history[-1].items[0] = replace(history[-1].items[0], done=True)
        self.assertFalse(any(row['source'] == 'jira' for row in analyze(history)['risks']))

    def test_snapshot_round_trip_and_unknown_history(self):
        """Serialized dates and IDs survive storage and one snapshot has no trend."""
        snapshot = demo_history()[-1]
        self.assertEqual(Snapshot.restore(snapshot.payload()), snapshot)
        self.assertIsNone(analyze([snapshot])['baseline_at'])
        with self.assertRaises(ValueError):
            analyze([])

    def test_disappeared_item_is_not_completed(self):
        """No completion is inferred when a source drops a task."""
        history = demo_history()
        history[-1].items = [item for item in history[-1].items if item.source != 'asana']
        analysis = analyze(history)
        asana = next(trend for trend in analysis['trends'] if trend['source'] == 'asana')
        self.assertEqual(asana['newly_done_observed'], [])


class ConnectorTests(unittest.TestCase):
    """Exercise real HTTP serialization with deterministic provider fixtures."""

    def test_asana_cursor_pagination_and_dependencies(self):
        """All pages and dependency blockers must be retained."""
        requests = []

        def respond(request):
            """Return a second page only after the cursor is forwarded."""
            requests.append(request)
            task = {'gid': str(len(requests)), 'name': 'Task', 'completed': False,
                    'dependencies': [{'gid': 'dep', 'completed': False}], 'custom_fields': []}
            return httpx.Response(200, json={'data': [task], 'next_page': {'offset': 'next'} if len(requests) == 1 else None})

        with patch.dict(os.environ, {'ASANA_ACCESS_TOKEN': 'test', 'ASANA_PROJECT_ID': 'p'}):
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                items = Collector(client).asana()
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.blocked for item in items))
        self.assertEqual(requests[1].url.params['offset'], 'next')

    def test_jira_active_sprint_and_links(self):
        """Jira normalizes sprint membership and unresolved inbound blocking links."""
        def respond(request):
            """Return one active sprint and its issue."""
            if request.url.path.endswith('/sprint'):
                return httpx.Response(200, json={'values': [{'id': 8, 'name': 'Week 8'}], 'isLast': True})
            return httpx.Response(200, json={'total': 1, 'issues': [{'key': 'PROJ-1', 'fields': {
                'summary': 'Build', 'status': {'name': 'Doing', 'statusCategory': {'key': 'indeterminate'}},
                'issuelinks': [{'type': {'inward': 'is blocked by'}, 'inwardIssue': {'key': 'PROJ-2'}}]}}]})
        with patch.dict(os.environ, {'JIRA_BASE_URL': 'https://jira.example.com', 'JIRA_EMAIL': 'test', 'JIRA_API_TOKEN': 'test', 'JIRA_BOARD_ID': '1'}):
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                item = Collector(client).jira()[0]
        self.assertTrue(item.blocked)
        self.assertEqual(item.sprint, '8: Week 8')
        self.assertEqual(item.url, 'https://jira.example.com/browse/PROJ-1')

    def test_notion_mapping_and_pagination(self):
        """Notion uses data sources and configurable task-property mappings."""
        requests = []

        def respond(request):
            """Return two Notion result pages."""
            requests.append(request)
            return httpx.Response(200, json={'results': [{'id': str(len(requests)), 'properties': {
                'Name': {'type': 'title', 'title': [{'plain_text': 'Task'}]},
                'Stage': {'type': 'status', 'status': {'name': 'Blocked'}}}}],
                'has_more': len(requests) == 1, 'next_cursor': 'cursor'})

        with patch.dict(os.environ, {'NOTION_API_TOKEN': 'test', 'NOTION_DATA_SOURCE_ID': 'ds', 'PM_NOTION_PROPERTIES': '{"status":"Stage"}'}):
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                items = Collector(client).notion()
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0].blocked)
        self.assertIn(b'"start_cursor":"cursor"', requests[1].content)
        self.assertEqual(notion_value({'type': 'date', 'date': None}), '')

    def test_page_limit_and_retry(self):
        """Never label truncated data successful and retry a throttled read."""
        with patch.dict(os.environ, {'PM_MAX_PAGES': '1'}):
            with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'issues': [{}], 'total': 2}))) as client:
                with self.assertRaises(SourceError):
                    Collector(client).jira_pages('https://jira.example.com', 'issues', ('u', 'p'), {})
        responses = [httpx.Response(429, headers={'Retry-After': '0'}), httpx.Response(200, json={'ok': True})]
        with httpx.Client(transport=httpx.MockTransport(lambda request: responses.pop(0))) as client:
            with patch('project2.status_agent.connectors.time.sleep'):
                self.assertTrue(Collector(client).request('GET', 'https://example.com')['ok'])

    def test_partial_failure_is_explicit(self):
        """Independent provider failure preserves good evidence and records missing coverage."""
        with patch.dict(os.environ, {'PM_SOURCES': 'jira,asana'}), patch.object(Collector, 'jira', side_effect=SourceError('failure')), patch.object(Collector, 'asana', return_value=[]):
            result = collect()
        self.assertNotEqual(result.coverage['jira'], 'ok')
        self.assertEqual(result.coverage['asana'], 'ok')

    def test_scope_isolation(self):
        """Changing project selection must isolate history without using secret values."""
        with patch.dict(os.environ, {'JIRA_BOARD_ID': '1'}):
            first = scope_id()
        with patch.dict(os.environ, {'JIRA_BOARD_ID': '2'}):
            self.assertNotEqual(first, scope_id())


class AgentTests(unittest.TestCase):
    """Verify evidence grounding, bounded requests and failure fallback."""

    def test_llm_receives_history_and_rules(self):
        """The API sees dated evidence with no server-side response storage."""
        with patch.dict(os.environ, {'PM_USE_LLM': 'true', 'OPENAI_API_KEY': 'test', 'OPENAI_MODEL': 'test'}), patch('project2.status_agent.agent.OpenAI') as model:
            request = model.return_value.__enter__.return_value.responses.create
            request.return_value.output_text = 'Evidence-based summary'
            self.assertEqual(evidence_answer(demo_history(), 'What is stuck?'), 'Evidence-based summary')
            self.assertIn('DEMO-12', request.call_args.kwargs['input'])
            self.assertFalse(request.call_args.kwargs['store'])
            self.assertIn('untrusted', request.call_args.kwargs['instructions'])

    def test_llm_failure_keeps_report_and_context_limit(self):
        """LLM failures cannot remove computed risks or silently truncate context."""
        with patch.dict(os.environ, {'PM_USE_LLM': 'true', 'PM_MAX_CONTEXT_CHARS': '1'}):
            with self.assertRaises(ValueError):
                evidence_answer(demo_history(), 'Question')
            self.assertIn('RED', weekly_report(demo_history()))

    def test_postgres_only_and_parameterized_storage(self):
        """Reject other databases and keep scope and evidence out of SQL interpolation."""
        with self.assertRaises(ValueError):
            Memory('sqlite:///history.db', 'scope')
        with patch('project2.status_agent.memory.psycopg.connect') as connect:
            memory = Memory('postgresql://example/test', "scope'quoted")
            memory.save(demo_history()[-1])
            call = connect.return_value.__enter__.return_value.execute.call_args
            self.assertNotIn("scope'quoted", call.args[0])
            self.assertEqual(call.args[1][0], "scope'quoted")


if __name__ == '__main__':
    unittest.main()
