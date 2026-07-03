"""MongoDB 采集服务测试。"""
from unittest.mock import patch, MagicMock
from django.test import TestCase

from monitoring.services.mongo_probe import probe_mongo, ProbeStatus


class _FakeClient:
    def __init__(self, status):
        self._status = status
    def admin(self):
        return self
    def command(self, cmd):
        if cmd == 'serverStatus':
            return self._status
        return {}
    def close(self): pass


class MongoProbeOk(TestCase):
    @patch('monitoring.services.mongo_probe.MongoClient')
    def test_probe_mongo_returns_metrics(self, mock_mc):
        mock_mc.return_value = _FakeClient({
            'connections': {'current': 10, 'available': 800},
            'opcounters': {'insert': 100, 'query': 50, 'update': 20, 'delete': 5, 'command': 200},
            'wiredTiger': {'cache': {"bytes currently in the cache": 16777216, "maximum bytes configured": 67108864}},
            'repl': {'secondary': True, 'lagSeconds': 1},
        })

        from sqlaudit.models import DataSource
        ds = DataSource.objects.create(
            name='test-mongo', db_type='mongo',
            host='127.0.0.1', port=27017,
        )

        result = probe_mongo(ds, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.OK)
        self.assertEqual(result.metrics['connections']['current'], 10)
        self.assertEqual(result.metrics['opcounters']['insert'], 100)
        self.assertTrue(result.metrics['replication']['is_secondary'])
        self.assertEqual(result.metrics['replication']['lag_seconds'], 1)


class MongoProbeError(TestCase):
    @patch('monitoring.services.mongo_probe.MongoClient')
    def test_probe_connect_error(self, mock_mc):
        from pymongo.errors import ServerSelectionTimeoutError
        mock_mc.side_effect = ServerSelectionTimeoutError('no replica')

        from sqlaudit.models import DataSource
        ds = DataSource.objects.create(
            name='err', db_type='mongo',
            host='127.0.0.1', port=27017,
        )
        result = probe_mongo(ds, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.ERROR)


class MongoProbeMisconfigured(TestCase):
    @patch('monitoring.services.mongo_probe.MongoClient')
    def test_probe_missing_host(self, mock_mc):
        from sqlaudit.models import DataSource
        ds = DataSource.objects.create(
            name='misconf', db_type='mongo',
            port=27017,  # 缺 host
        )
        result = probe_mongo(ds, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.MISCONFIGURED)
        mock_mc.assert_not_called()
