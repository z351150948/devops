"""Redis 采集服务测试（D-2b 降级 — 全部 skip）。

注：本环境无 pytest 依赖，沿用 Django `unittest.skip` 装饰器实现 D-2b skip 语义。
若日后引入 pytest 测试 runner，可改回 `@pytest.mark.skipif(True, reason="D-2b 降级")`。
"""
from unittest import skip
from django.test import TestCase

from monitoring.services.redis_probe import probe_redis, ProbeStatus


@skip("D-2b 降级：Redis 监控未启用")
class RedisProbeStub(TestCase):
    def test_probe_redis_returns_misconfigured(self):
        from sqlaudit.models import DataSource
        ds = DataSource.objects.create(
            name='stub-redis', db_type='mongodb',  # 注：db_type 选 mongodb 以便创建（无 redis choice）
            host='127.0.0.1', port=6379,
        )
        result = probe_redis(ds, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.MISCONFIGURED)
        self.assertIn('D-2b', result.error or '')