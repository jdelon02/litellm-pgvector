"""Search API contract tests; database and embedding calls are isolated."""
import unittest
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from models import VectorStoreSearchRequest

# Prisma needs a generated client in production. No generated database client is
# needed to test the real HTTP routes with an isolated database boundary.
prisma_stub = ModuleType('prisma')
prisma_stub.Prisma = MagicMock()
with patch.dict('sys.modules', {'prisma': prisma_stub}):
    import main


class ProjectFilterTests(unittest.TestCase):
    def setUp(self):
        self.db = AsyncMock()
        self.db.query_raw.side_effect = [[{'id': 'vs-test'}], []]
        self.embedding = AsyncMock(return_value=[0.1, 0.2])
        self.db_patch = patch.object(main, 'db', self.db)
        self.embedding_patch = patch.object(main, 'generate_query_embedding', self.embedding)
        self.db_patch.start()
        self.embedding_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.embedding_patch.stop)
        main.app.dependency_overrides[main.get_api_key] = lambda: 'test-key'
        self.addCleanup(main.app.dependency_overrides.clear)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def search(self, payload, prefix='/v1'):
        return self.client.post(prefix + '/vector_stores/vs-test/search', json=dict(query='rules', **payload))

    def test_project_filter_is_parameterized_on_both_routes(self):
        for prefix in ('/v1', ''):
            with self.subTest(prefix=prefix):
                self.db.query_raw.side_effect = [[{'id': 'vs-test'}], []]
                project = "project' OR 1=1 --"
                response = self.search({'project_id': project}, prefix)
                self.assertEqual(response.status_code, 200, response.text)
                sql, *params = self.db.query_raw.call_args.args
                self.assertIn('metadata->>$3 = $4', sql)
                self.assertNotIn(project, sql)
                self.assertEqual(params, ['[0.1,0.2]', 'vs-test', 'project_id', project])
                self.assertEqual(response.json()['data'], [])

    def test_omitted_or_null_project_preserves_legacy_filters(self):
        for payload in ({}, {'project_id': None}):
            with self.subTest(payload=payload):
                self.db.query_raw.side_effect = [[{'id': 'vs-test'}], []]
                response = self.search(dict(payload, filters={'category': 'support'}))
                self.assertEqual(response.status_code, 200)
                sql, *params = self.db.query_raw.call_args.args
                self.assertEqual(params, ['[0.1,0.2]', 'vs-test', 'category', 'support'])
                self.assertNotIn('project_id', sql)

    def test_omitted_and_null_without_filters_add_no_restriction(self):
        for payload in ({}, {'project_id': None}):
            self.db.query_raw.side_effect = [[{'id': 'vs-test'}], []]
            response = self.search(payload)
            self.assertEqual(response.status_code, 200)
            sql, *params = self.db.query_raw.call_args.args
            self.assertNotIn('->>', sql)
            self.assertEqual(params, ['[0.1,0.2]', 'vs-test'])

    def test_project_combines_with_other_filters_using_and(self):
        response = self.search({'project_id': 'scriptwriting', 'filters': {'category': 'rules'}})
        self.assertEqual(response.status_code, 200)
        sql, *params = self.db.query_raw.call_args.args
        self.assertIn('metadata->>$3 = $4 AND metadata->>$5 = $6', sql)
        self.assertEqual(params, ['[0.1,0.2]', 'vs-test', 'category', 'rules', 'project_id', 'scriptwriting'])

    def test_matching_legacy_project_filter_is_applied_once(self):
        response = self.search({'project_id': 'scriptwriting', 'filters': {'project_id': 'scriptwriting'}})
        self.assertEqual(response.status_code, 200)
        sql, *params = self.db.query_raw.call_args.args
        self.assertEqual(sql.count('->>'), 1)
        self.assertEqual(params[-2:], ['project_id', 'scriptwriting'])

    def test_project_filter_uses_configured_metadata_column(self):
        with patch.object(main.settings.db_fields, 'metadata_field', 'document_metadata'):
            response = self.search({'project_id': 'scriptwriting', 'return_metadata': False})
        self.assertEqual(response.status_code, 200)
        sql = self.db.query_raw.call_args.args[0]
        self.assertIn('document_metadata->>$3 = $4', sql)

    def test_invalid_project_returns_422_before_backend_work(self):
        payloads = [{'project_id': value} for value in ('', ' \t\n', 123, [], {})]
        payloads += [{'project_id': 'one', 'filters': {'project_id': value}} for value in ('two', None, 123)]
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.search(payload)
                self.assertEqual(response.status_code, 422, response.text)
        self.db.query_raw.assert_not_awaited()
        self.embedding.assert_not_awaited()

    def test_request_does_not_mutate_callers_filter_dictionary(self):
        filters = {'category': 'rules'}
        parsed = VectorStoreSearchRequest(query='rules', project_id='scriptwriting', filters=filters)
        self.assertEqual(parsed.project_id, 'scriptwriting')
        self.assertEqual(filters, {'category': 'rules'})

    def test_query_markers_filter_both_routes_and_are_removed_before_embedding(self):
        for prefix in ('/v1', ''):
            for marker in ('project_id: scriptwriting', 'PROJECT ID=scriptwriting', 'project : scriptwriting'):
                with self.subTest(prefix=prefix, marker=marker):
                    self.db.query_raw.side_effect = [[{'id': 'vs-test'}], []]
                    response = self.client.post(prefix + '/vector_stores/vs-test/search',
                                                json={'query': marker + ' What can the Artist author?'})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.embedding.assert_awaited_with('What can the Artist author?')
                    self.assertEqual(response.json()['search_query'], 'What can the Artist author?')
                    self.assertEqual(self.db.query_raw.call_args.args[-2:], ('project_id', 'scriptwriting'))

    def test_markers_support_repetition_quoted_names_and_end_position(self):
        cases = [
            ('find rules project_id: scriptwriting', 'scriptwriting', 'find rules'),
            ('project: scriptwriting find project ID=scriptwriting rules', 'scriptwriting', 'find rules'),
            ('project: "My Project" find rules', 'My Project', 'find rules'),
            ("project_id='My Project' find rules", 'My Project', 'find rules'),
        ]
        for query, project, clean in cases:
            with self.subTest(query=query):
                parsed = VectorStoreSearchRequest(query=query)
                self.assertEqual(parsed.project_id, project)
                self.assertEqual(parsed.query, clean)

    def test_bad_or_conflicting_markers_fail_before_backend_work(self):
        cases = [
            {'query': 'project: one project_id: two find rules'},
            {'query': 'project: one find rules', 'project_id': 'two'},
            {'query': 'project: one find rules', 'filters': {'project_id': 'two'}},
            {'query': 'find rules project_id:'},
            {'query': 'project: "" find rules'},
            {'query': 'project: "unclosed find rules'},
            {'query': 'project: one'},
            {'query': 'project_id: \nfind rules'},
            {'query': 'project: "  " find rules'},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post('/v1/vector_stores/vs-test/search', json=payload)
                self.assertEqual(response.status_code, 422, response.text)
        self.db.query_raw.assert_not_awaited()
        self.embedding.assert_not_awaited()

    def test_queries_without_markers_are_unchanged(self):
        for query in ('Search the project for rules', '  find  rules\nplease ', 'metadata.project_id matters'):
            parsed = VectorStoreSearchRequest(query=query)
            self.assertEqual(parsed.query, query)
            self.assertIsNone(parsed.project_id)

    def test_matching_marker_and_explicit_filters_are_allowed(self):
        parsed = VectorStoreSearchRequest(query='project: scriptwriting rules',
                                          project_id='scriptwriting', filters={'project_id': 'scriptwriting'})
        self.assertEqual(parsed.query, 'rules')
        self.assertEqual(parsed.project_id, 'scriptwriting')


if __name__ == '__main__':
    unittest.main()
