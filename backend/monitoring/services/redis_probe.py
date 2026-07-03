"""Redis 数据库采集 stub（D-2b 降级 — 始终返回 misconfigured）。

`sqlaudit.DataSource.db_type` choices 不含 `redis`（仅 mysql/mongodb/polardb），
且受保护路径禁止改 sqlaudit 模型。本函数仅作为占位存在，api.py 不再分发 redis 分支。
"""
from dataclasses import dataclass, asdict
from typing import Optional


class ProbeStatus:
    OK = 'ok'
    ERROR = 'error'
    TIMEOUT = 'timeout'
    MISCONFIGURED = 'misconfigured'


@dataclass
class ProbeResult:
    status: str = ProbeStatus.MISCONFIGURED
    duration_ms: int = 0
    metrics: Optional[dict] = None
    error: Optional[str] = 'Redis 监控未启用（D-2b 降级）'

    def to_dict(self) -> dict:
        return asdict(self)


def probe_redis(ds, timeout_seconds: int = 5) -> ProbeResult:
    """占位：始终返回 misconfigured（plan 任务 6 D-2b 模式）。"""
    return ProbeResult()