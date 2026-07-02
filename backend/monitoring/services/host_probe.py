"""主机 SSH 采集（复用 ops.host_tasks 的 SSH 5 步走）。"""
import socket
import time
from dataclasses import dataclass, asdict
from typing import Optional

import paramiko

from ops.host_tasks import open_ssh_client, execute_remote_command


class ProbeStatus:
    OK = 'ok'
    ERROR = 'error'
    TIMEOUT = 'timeout'
    MISCONFIGURED = 'misconfigured'


@dataclass
class ProbeResult:
    status: str
    duration_ms: int = 0
    metrics: Optional[dict] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# 5 条采集命令 + 解析
_PROBE_COMMANDS = [
    ('cpu', 'cat /proc/loadavg'),
    ('memory', 'free -m'),
    ('disk', 'df -BG --output=source,size,used,avail,pcent,target'),
    ('uptime', 'cat /proc/uptime'),
    ('network', 'cat /proc/net/dev'),
]


def _parse_loadavg(output: str) -> dict:
    parts = output.strip().split()
    return {
        'load1': float(parts[0]) if len(parts) > 0 else 0.0,
        'load5': float(parts[1]) if len(parts) > 1 else 0.0,
        'load15': float(parts[2]) if len(parts) > 2 else 0.0,
    }


def _parse_memory(output: str) -> dict:
    # 输出: "              total        used        free\nMem:           16000        4800       11200"
    for line in output.splitlines():
        if line.startswith('Mem:'):
            parts = line.split()
            total_mb = int(parts[1])
            used_mb = int(parts[2])
            return {
                'total_mb': total_mb,
                'used_mb': used_mb,
                'usage_pct': round(used_mb / total_mb * 100, 1) if total_mb else 0.0,
            }
    return {'total_mb': 0, 'used_mb': 0, 'usage_pct': 0.0}


def _parse_disk(output: str) -> list:
    # 跳表头；每行: Filesystem 1G-blocks Used Available Use% Mounted on
    result = []
    lines = output.splitlines()[1:]  # skip header
    for line in lines:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        # Use% 形式如 "45%"
        use_pct = parts[4].rstrip('%')
        try:
            use_pct_num = int(use_pct)
        except ValueError:
            continue
        result.append({
            'mount': parts[5],
            'size_gb': int(parts[1].rstrip('G')) if parts[1].endswith('G') else 0,
            'used_pct': use_pct_num,
        })
    return result


def _parse_uptime(output: str) -> int:
    return int(float(output.split()[0]))


def _parse_network(output: str) -> dict:
    # 找 eth0 行（第一个非 lo 且非 sit/tun 等虚拟接口）
    rx_bytes = tx_bytes = 0
    for line in output.splitlines():
        if ':' not in line:
            continue
        iface_name = line.split(':', 1)[0].strip()
        if iface_name in ('lo', 'sit0', 'tunl0') or iface_name.startswith(('veth', 'docker', 'br-')):
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        rx_bytes += int(parts[1])
        tx_bytes += int(parts[9])
    return {'rx_bytes': rx_bytes, 'tx_bytes': tx_bytes}


def probe_host(host, timeout_seconds: int = 5) -> ProbeResult:
    """对一台主机做 on-demand 采集。失败时返回 status=error/timeout/misconfigured，**不抛异常**。"""
    started = time.monotonic()

    # 错配检查：密码 / 私钥为空
    if not (host.ssh_password or '').strip():
        return ProbeResult(
            status=ProbeStatus.MISCONFIGURED,
            duration_ms=int((time.monotonic() - started) * 1000),
            error='SSH 凭据缺失（ssh_password 为空）',
        )

    try:
        client = open_ssh_client(host, timeout_seconds=timeout_seconds)
    except paramiko.AuthenticationException:
        return ProbeResult(
            status=ProbeStatus.ERROR,
            duration_ms=int((time.monotonic() - started) * 1000),
            error='SSH 认证失败',
        )
    except (paramiko.SSHException, socket.timeout, OSError) as exc:
        # socket.timeout 包含 connection timeout；OSError 包含 network unreachable
        if isinstance(exc, socket.timeout):
            return ProbeResult(
                status=ProbeStatus.TIMEOUT,
                duration_ms=int((time.monotonic() - started) * 1000),
                error=f'SSH 连接超时（>{timeout_seconds}s）',
            )
        return ProbeResult(
            status=ProbeStatus.ERROR,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=f'SSH 不可达：{exc}',
        )

    try:
        metrics = {}
        for name, cmd in _PROBE_COMMANDS:
            try:
                _, output, _ = execute_remote_command(client, cmd, timeout_seconds=timeout_seconds)
            except (paramiko.SSHException, socket.timeout):
                metrics = {'partial': True, 'last_successful': name}
                # 一次失败不中断整次采集；标记为 timeout
                return ProbeResult(
                    status=ProbeStatus.TIMEOUT,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    metrics=metrics,
                    error=f'命令 {cmd} 超时',
                )
            if name == 'cpu':
                metrics['cpu'] = _parse_loadavg(output)
            elif name == 'memory':
                metrics['memory'] = _parse_memory(output)
            elif name == 'disk':
                metrics['disk'] = _parse_disk(output)
            elif name == 'uptime':
                metrics['uptime_seconds'] = _parse_uptime(output)
            elif name == 'network':
                metrics['network'] = _parse_network(output)

        return ProbeResult(
            status=ProbeStatus.OK,
            duration_ms=int((time.monotonic() - started) * 1000),
            metrics=metrics,
            error=None,
        )
    finally:
        client.close()