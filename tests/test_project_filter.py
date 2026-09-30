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

    def test_search_filters_by_vector_store_id_as_project_id(self):
        """Searching a vector store automatically filters by metadata.project_id = vector_store_id."""
        for prefix in ('/v1', ''):
            with self.subTest(prefix=prefix):
                self.db.query_raw.side_effect = [[{'id': 'vs-test'}], []]
                response = self.search({}, prefix)
                self.assertEqual(response.status_code, 200, response.text)
                sql, *params = self.db.query_raw.call_args.args
                self.assertIn('metadata->>\'project_id\' = $3', sql)
                self.assertEqual(params, ['[0.1,0.2]', 'vs-test', 'vs-test'])
                self.assertEqual(response.json()['data'], [])

    def test_matching_project_id_is_allowed(self):
        """Providing project_id matching the vector store name is allowed."""
        for prefix in ('/v1', ''):
            with self.subTest(prefix=prefix):
                self.db.query_raw.side_effect = [[{'id': 'vs-test'}], []]
                response = self.search({'project_id': 'vs-test'}, prefix)
                self.assertEqual(response.status_code, 200, response.text)
                sql, *params = self.db.query_raw.call_args.args
                self.assertIn('metadata->>\'project_id\' = $3', sql)
                self.assertEqual(params, ['[0.1,0.2]', 'vs-test', 'vs-test'])

    def test_mismatched_project_id_returns_422(self):
        """Providing project_id NOT matching the vector store name returns 422."""
        payloads = [
            {'project_id': 'other-project'},
            {'filters': {'project_id': 'other-project'}},
            {'project_id': 'vs-test', 'filters': {'project_id': 'other-project'}},  # conflict via filter
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.search(payload)
                self.assertEqual(response.status_code, 422, response.text)
        self.db.query_raw.assert_not_awaited()
        self.embedding.assert_not_awaited()

    def test_query_marker_must_match_vector_store_id(self):
        """Query marker project_id must match the vector store name."""
        # Marker matches vs-test
        self.db.query_raw.side_effect = [[{'id': 'vs-test'}], []]
        response = self.client.post('/v1/vector_stores/vs-test/search',
                                    json={'query': 'project_id: vs-test What are the rules?'})
        self.assertEqual(response.status_code, 200, response.text)
        self.embedding.assert_awaited_with('What are the rules?')
        sql, *params = self.db.query_raw.call_args.args
        self.assertEqual(params, ['[0.1,0.2]', 'vs-test', 'vs-test'])

    def test_query_marker_mismatch_returns_422(self):
        """Query marker project_id NOT matching returns 422."""
        response = self.client.post('/v1/vector_stores/vs-test/search',
                                    json={'query': 'project_id: other-project What are the rules?'})
        self.assertEqual(response.status_code, 422, response.text)
        self.db.query_raw.assert_not_awaited()
        self.embedding.assert_not_awaited()

    def test_project_id_filter_combines_with_other_filters_using_and(self):
        response = self.search({'filters': {'category': 'rules'}})
        self.assertEqual(response.status_code, 200)
        sql, *params = self.db.query_raw.call_args.args
        self.assertIn('metadata->>\'project_id\' = $3 AND metadata->>$4 = $5', sql)
        self.assertEqual(params, ['[0.1,0.2]', 'vs-test', 'vs-test', 'category', 'rules'])

    def test_project_id_uses_configured_metadata_and_project_id_columns(self):
        with patch.object(main.settings.db_fields, 'metadata_field', 'document_metadata'):
            with patch.object(main.settings.db_fields, 'project_id_field', 'proj_id'):
                response = self.search({'return_metadata': False})
        self.assertEqual(response.status_code, 200)
        sql = self.db.query_raw.call_args.args[0]
        self.assertIn('document_metadata->>\'proj_id\' = $3', sql)
        self.assertEqual(list(self.db.query_raw.call_args.args[1:]), ['[0.1,0.2]', 'vs-test', 'vs-test'])

    def test_invalid_project_returns_422_before_backend_work(self):
        payloads = [{'project_id': value} for value in ('', ' \t\n', 123, [], {})]
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.search(payload)
                self.assertEqual(response.status_code, 422, response.text)
        self.db.query_raw.assert_not_awaited()
        self.embedding.assert_not_awaited()

    def test_request_does_not_mutate_callers_filter_dictionary(self):
        filters = {'category': 'rules'}
        parsed = VectorStoreSearchRequest(query='rules', project_id='vs-test', filters=filters)
        self.assertEqual(parsed.project_id, 'vs-test')
        self.assertEqual(filters, {'category': 'rules'})

    def test_query_markers_are_removed_before_embedding(self):
        for marker in ('project_id: vs-test', 'PROJECT ID=vs-test', 'project : vs-test'):
            with self.subTest(marker=marker):
                self.db.query_raw.side_effect = [[{'id': 'vs-test'}], []]
                response = self.client.post('/v1/vector_stores/vs-test/search',
                                            json={'query': marker + ' What can the Artist author?'})
                self.assertEqual(response.status_code, 200, response.text)
                self.embedding.assert_awaited_with('What can the Artist author?')
                self.assertEqual(response.json()['search_query'], 'What can the Artist author?')

    def test_markers_support_repetition_quoted_names_and_end_position(self):
        cases = [
            ('find rules project_id: vs-test', 'vs-test', 'find rules'),
            ('project: vs-test find project ID=vs-test rules', 'vs-test', 'find rules'),
            ('project: "vs-test" find rules', 'vs-test', 'find rules'),
            ("project_id='vs-test' find rules", 'vs-test', 'find rules'),
        ]
        for query, project, clean in cases:
            with self.subTest(query=query):
                parsed = VectorStoreSearchRequest(query=query)
                self.assertEqual(parsed.project_id, project)
                self.assertEqual(parsed.query, clean)

    def test_bad_or_conflicting_markers_fail_before_backend_work(self):
        cases = [
            {'query': 'project: one project_id: two find rules'},
            {'query': 'project_id:', 'project_id': 'vs-test'},
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


if __name__ == '__main__':
    unittest.main()
