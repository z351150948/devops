"""主机采集服务测试。"""
import socket
from unittest.mock import patch, MagicMock

from django.test import TestCase

from monitoring.services.host_probe import (
    probe_host,
    ProbeResult,
    ProbeStatus,
)


class _FakeSsh:
    """模拟 paramiko.SSHClient + exec_command。"""
    def __init__(self, output_map):
        self._output_map = output_map  # {cmd_substr: output_str}
        self._closed = False

    def set_missing_host_key_policy(self, _): pass
    def connect(self, **kwargs): pass

    def exec_command(self, cmd, timeout=None):
        # 根据 cmd 找匹配的 output
        for substr, output in self._output_map.items():
            if substr in cmd:
                chan = MagicMock()
                chan.recv_exit_status = MagicMock(return_value=0)
                stdin = MagicMock()
                stdout = MagicMock()
                stdout.read = MagicMock(return_value=output.encode('utf-8'))
                stdout.channel = chan
                stderr = MagicMock()
                stderr.read = MagicMock(return_value=b'')
                return stdin, stdout, stderr
        chan = MagicMock()
        chan.recv_exit_status = MagicMock(return_value=1)
        stdin = MagicMock()
        stdout = MagicMock()
        stdout.read = MagicMock(return_value=b'')
        stdout.channel = chan
        stderr = MagicMock()
        stderr.read = MagicMock(return_value=b'command not found')
        return stdin, stdout, stderr

    def close(self):
        self._closed = True


class HostProbeOk(TestCase):
    @patch('monitoring.services.host_probe.open_ssh_client')
    def test_probe_normal_host_returns_metrics(self, mock_open):
        # 模拟 /proc/loadavg + free -m + df + uptime 输出
        mock_open.return_value = _FakeSsh({
            '/proc/loadavg': '0.32 0.28 0.31 1/123 4567\n',
            'free -m': '              total        used        free\nMem:           16000        4800       11200\n',
            'df -BG': 'Filesystem     1G-blocks  Used Available Use% Mounted on\n/dev/sda1            100G    45G    55G  45% /\n',
            'uptime': ' 1234567.89 12345.67\n',
            '/proc/net/dev': 'eth0: 1234567 0 0 0 0 0 0 0 7654321 0 0 0 0 0 0 0\n',
        })

        from ops.models import Host
        host = Host.objects.create(
            hostname='node-01', ip_address='10.10.30.100',
            ssh_port=22, ssh_user='root', ssh_password='x',
        )

        result = probe_host(host, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.OK)
        self.assertIsNone(result.error)
        self.assertIn('cpu', result.metrics)
        self.assertEqual(result.metrics['memory']['total_mb'], 16000)
        self.assertEqual(result.metrics['memory']['used_mb'], 4800)
        self.assertEqual(len(result.metrics['disk']), 1)
        self.assertEqual(result.metrics['disk'][0]['mount'], '/')
        self.assertEqual(result.metrics['uptime_seconds'], 1234567)


class HostProbeAuthError(TestCase):
    @patch('monitoring.services.host_probe.open_ssh_client')
    def test_probe_auth_error_returns_error_status(self, mock_open):
        import paramiko
        mock_open.side_effect = paramiko.AuthenticationException()

        from ops.models import Host
        host = Host.objects.create(
            hostname='node-02', ip_address='10.10.30.101',
            ssh_port=22, ssh_user='root', ssh_password='wrong',
        )

        result = probe_host(host, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.ERROR)
        self.assertIn('认证失败', result.error)


class HostProbeTimeout(TestCase):
    @patch('monitoring.services.host_probe.open_ssh_client')
    def test_probe_timeout_returns_timeout_status(self, mock_open):
        mock_open.side_effect = socket.timeout()

        from ops.models import Host
        host = Host.objects.create(
            hostname='node-03', ip_address='10.10.30.102',
            ssh_port=22, ssh_user='root', ssh_password='x',
        )

        result = probe_host(host, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.TIMEOUT)


class HostProbeMisconfigured(TestCase):
    @patch('monitoring.services.host_probe.open_ssh_client')
    def test_probe_missing_password_returns_misconfigured(self, mock_open):
        from ops.models import Host
        host = Host.objects.create(
            hostname='node-04', ip_address='10.10.30.103',
            ssh_port=22, ssh_user='root', ssh_password='',  # 空凭据
        )

        result = probe_host(host, timeout_seconds=5)
        self.assertEqual(result.status, ProbeStatus.MISCONFIGURED)
        # 验证 open_ssh_client 未被调用
        mock_open.assert_not_called()