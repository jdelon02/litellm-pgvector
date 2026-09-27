"""Exercise date serialization on real HTTP routes with an isolated database."""
import unittest
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

prisma_stub = ModuleType('prisma')
prisma_stub.Prisma = MagicMock()
with patch.dict('sys.modules', {'prisma': prisma_stub}):
    import main


class VectorStoreDateTests(unittest.TestCase):
    def test_optional_dates_on_create_and_list(self):
        epoch = 1780000000
        instant = datetime.fromtimestamp(epoch, timezone.utc)
        cases = [None, instant, instant.isoformat(), instant.isoformat().replace('+00:00', 'Z'),
                 '2026-05-28T22:26:40+02:00', instant.replace(tzinfo=None)]
        with patch.object(main, 'db', AsyncMock()) as db, TestClient(main.app) as client:
            main.app.dependency_overrides[main.get_api_key] = lambda: 'test-key'
            self.addCleanup(main.app.dependency_overrides.clear)
            for field in ('expires_at', 'last_active_at'):
                for value in cases:
                    for method in ('get', 'post'):
                        with self.subTest(field=field, value=value, method=method):
                            row = dict(id='vs-test', name='test', created_at_timestamp=epoch,
                                       usage_bytes=0, file_counts=None, status='completed',
                                       expires_after=None, expires_at=None, last_active_at=None, metadata={})
                            row[field] = value
                            db.query_raw.return_value = [row]
                            response = (client.get('/v1/vector_stores') if method == 'get' else
                                        client.post('/v1/vector_stores', json={'name': 'test'}))
                            self.assertEqual(response.status_code, 200, response.text)
                            result = response.json()['data'][0] if method == 'get' else response.json()
                            self.assertEqual(result[field], None if value is None else epoch)
                            self.assertEqual(result['created_at'], epoch)


if __name__ == '__main__':
    unittest.main()
