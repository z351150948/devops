"""监控 API 集成测试：RBAC + 端点 + 单 host 失败不中断。"""
import paramiko
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from monitoring.services.host_probe import ProbeResult, ProbeStatus
from monitoring.tests.test_host_probe import _FakeSsh
from ops.models import Host
from rbac.models import Role
from rbac.services import ensure_builtin_rbac
from sqlaudit.models import DataSource


def _grant_permission(user, code: str):
    """测试辅助：给用户赋予单个权限码（新建一次性角色）。"""
    perm = Role.objects.get(code='platform-admin').permissions.get(code=code)
    role = Role.objects.create(
        code=f'test-{code}-{user.pk}',
        name=f'Test {code}',
        description='test_api 临时角色',
    )
    role.permissions.add(perm)
    user.rbac_roles.add(role)


class HostProbeApiTestCase(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        User = get_user_model()
        self.user = User.objects.create_user(username='tester', password='x')
        self.user.is_superuser = False
        self.user.save()

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_no_permission_returns_403(self):
        Host.objects.create(
            hostname='h-1', ip_address='10.0.0.1',
            ssh_port=22, ssh_user='root', ssh_password='x',
        )
        resp = self.client.post('/api/monitoring/hosts/probe/', {}, format='json')
        self.assertEqual(resp.status_code, 403)

    @patch('monitoring.api._bulk_host_probe')
    def test_with_permission_returns_results(self, mock_bulk):
        Host.objects.create(
            hostname='h-1', ip_address='10.0.0.1',
            ssh_port=22, ssh_user='root', ssh_password='x',
        )
        Host.objects.create(
            hostname='h-2', ip_address='10.0.0.2',
            ssh_port=22, ssh_user='root', ssh_password='x',
        )
        mock_bulk.return_value = [
            ProbeResult(status=ProbeStatus.OK, duration_ms=100, metrics={'cpu': {'load1': 0.1}}),
            ProbeResult(status=ProbeStatus.ERROR, duration_ms=50, error='auth failed'),
        ]

        # 给用户加权限
        _grant_permission(self.user, 'monitoring.host.view')

        resp = self.client.post('/api/monitoring/hosts/probe/', {}, format='json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['summary']['total'], 2)
        self.assertEqual(data['summary']['ok'], 1)
        self.assertEqual(data['summary']['error'], 1)
        # 单 host 失败不中断：响应包含 2 项而非 1 项
        self.assertEqual(len(data['results']), 2)

    @patch('monitoring.services.host_probe.open_ssh_client')
    def test_real_partial_failure_does_not_break_bulk(self, mock_open):
        """1 host 凭据错 + 1 host 正常：响应含 1 ok + 1 error。"""
        h_bad = Host.objects.create(
            hostname='h-bad', ip_address='10.0.0.99',
            ssh_port=22, ssh_user='root', ssh_password='wrong',
        )
        h_good = Host.objects.create(
            hostname='h-good', ip_address='10.0.0.100',
            ssh_port=22, ssh_user='root', ssh_password='right',
        )

        # h_bad 抛 AuthException，h_good 正常
        def open_side_effect(host, timeout_seconds):
            if host.id == h_bad.id:
                raise paramiko.AuthenticationException()
            # good 路径：返回伪 SSH client
            return _FakeSsh({
                '/proc/loadavg': '0.1 0.1 0.1 1/1 1\n',
                'free -m': 'Mem: 1024 512 512\n',
                'df -BG': '/dev/sda1 10G 5G 5G 50% /\n',
                'uptime': '1.0 0.5\n',
                '/proc/net/dev': 'eth0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n',
            })
        mock_open.side_effect = open_side_effect

        _grant_permission(self.user, 'monitoring.host.view')

        resp = self.client.post('/api/monitoring/hosts/probe/', {}, format='json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        statuses = {it['hostname']: it['status'] for it in data['results']}
        self.assertEqual(statuses.get('h-bad'), 'error')
        self.assertEqual(statuses.get('h-good'), 'ok')


class DatabaseProbeApiTestCase(TestCase):
    def setUp(self):
        ensure_builtin_rbac()
        User = get_user_model()
        self.user = User.objects.create_user(username='tester2', password='x')
        self.user.is_superuser = False
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_no_permission_returns_403(self):
        # D-2b flat schema：host/port/user/password 是顶层字段
        DataSource.objects.create(
            name='d1', db_type='mysql',
            host='127.0.0.1', port=3306,
            user='root', password='x',
        )
        resp = self.client.post('/api/monitoring/databases/probe/', {}, format='json')
        self.assertEqual(resp.status_code, 403)
