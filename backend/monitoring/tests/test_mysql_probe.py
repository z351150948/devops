"""MySQL 采集服务测试。"""
from unittest.mock import patch, MagicMock
from django.test import TestCase

from monitoring.services.mysql_probe import probe_mysql, ProbeStatus


class _FakeCursor:
    def __init__(self, rows):
        self._data = rows  # 保留 dict 引用
        self._current_key = None

    def execute(self, sql):
        if 'show global status' in sql.lower():
            self._current_key = 'status'
        elif 'show slave status' in sql.lower():
            self._current_key = 'slave'
        return self

    def fetchall(self):
        return self._data.get(self._current_key, [])

    def fetchone(self):
        rows = self._data.get(self._current_key, [])
        return rows[0] if rows else None

    def close(self): pass


class _FakeConn:
    def __init__(self, data):
        self._data = data

    def cursor(self, *args, **kwargs):
        # 每次调用 cursor() 都返回新实例（防止上次的 _current_key 串扰）
        return _FakeCursor(self._data)

    def close(self): pass


class MySQLProbeOk(TestCase):
    @patch('monitoring.services.mysql_probe.pymysql.connect')
    def test_probe_mysql_returns_metrics(self, mock_connect):
        mock_connect.return_value = _FakeConn({
            'status': [
                ('Threads_connected', 12),
                ('Questions', 100000),
                ('Slow_queries', 5),
                ('Innodb_buffer_pool_read_requests', 1000),
                ('Innodb_buffer_pool_reads', 10),
            ],
            'slave': [],
        })

        from sqlaudit.models import DataSource
        ds = DataSource.objects.create(
            name='test-mysql', db_type='mysql',
            host='127.0.0.1', port=3306, user='root', password='x',
        )

        result = probe_mysql(ds, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.OK)
        self.assertEqual(result.metrics['threads_connected'], 12)
        self.assertEqual(result.metrics['questions'], 100000)
        self.assertEqual(result.metrics['slow_queries'], 5)
        # buffer pool hit rate: 1 - 10/1000 = 0.99
        self.assertAlmostEqual(result.metrics['innodb_buffer_pool_hit_rate'], 0.99, places=2)


class MySQLProbeMisconfigured(TestCase):
    @patch('monitoring.services.mysql_probe.pymysql.connect')
    def test_probe_missing_host_returns_misconfigured(self, mock_connect):
        from sqlaudit.models import DataSource
        ds = DataSource.objects.create(
            name='misconf', db_type='mysql',
            user='root', password='x',  # 缺 host
        )
        result = probe_mysql(ds, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.MISCONFIGURED)
        mock_connect.assert_not_called()


class MySQLProbeError(TestCase):
    @patch('monitoring.services.mysql_probe.pymysql.connect')
    def test_probe_connect_error_returns_error(self, mock_connect):
        import pymysql
        mock_connect.side_effect = pymysql.OperationalError(2003, "Can't connect")

        from sqlaudit.models import DataSource
        ds = DataSource.objects.create(
            name='err', db_type='mysql',
            host='127.0.0.1', port=3306, user='root', password='x',
        )
        result = probe_mysql(ds, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.ERROR)
        self.assertIn('连接失败', result.error)