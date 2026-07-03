"""MongoDB 数据库采集（pymongo + serverStatus() 解析）。"""
import time
from dataclasses import dataclass, asdict
from typing import Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from sqlaudit.models import DataSource


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


def probe_mongo(ds: DataSource, timeout_seconds: int = 5) -> ProbeResult:
    started = time.monotonic()
    # D-2b flat schema：从 ds.host/ds.port/ds.user/ds.password 组装 params
    params = {
        'host': ds.host,
        'port': ds.port or 27017,
        'user': ds.user,
        'password': ds.password or '',
    }

    if not params.get('host'):
        return ProbeResult(
            status=ProbeStatus.MISCONFIGURED,
            duration_ms=int((time.monotonic() - started) * 1000),
            error='凭据缺失字段：host',
        )

    try:
        client = MongoClient(
            host=params['host'],
            port=int(params.get('port', 27017)),
            username=params.get('user') or None,
            password=params.get('password') or None,
            serverSelectionTimeoutMS=timeout_seconds * 1000,
            connectTimeoutMS=timeout_seconds * 1000,
        )
        status = client.admin().command('serverStatus')
        client.close()
    except PyMongoError as exc:
        return ProbeResult(
            status=ProbeStatus.ERROR,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=f'MongoDB 连接失败：{exc}',
        )
    except OSError as exc:
        return ProbeResult(
            status=ProbeStatus.ERROR,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=f'MongoDB 不可达：{exc}',
        )

    # 解析
    connections = status.get('connections', {})
    opcounters = status.get('opcounters', {})
    wt = status.get('wiredTiger', {}).get('cache', {})
    cache_used = int(wt.get('bytes currently in the cache', 0))
    cache_max = int(wt.get('maximum bytes configured', 0))
    repl = status.get('repl', {})

    metrics = {
        'connections': {
            'current': int(connections.get('current', 0)),
            'available': int(connections.get('available', 0)),
        },
        'opcounters': {
            'insert': int(opcounters.get('insert', 0)),
            'query': int(opcounters.get('query', 0)),
            'update': int(opcounters.get('update', 0)),
            'delete': int(opcounters.get('delete', 0)),
            'command': int(opcounters.get('command', 0)),
        },
        'wiredtiger': {
            'cache_used_mb': round(cache_used / 1024 / 1024, 2),
            'cache_max_mb': round(cache_max / 1024 / 1024, 2),
        },
        'replication': {
            'is_secondary': bool(repl.get('secondary', False)),
            'lag_seconds': int(repl.get('lagSeconds', 0)) if repl.get('lagSeconds') is not None else 0,
        },
    }
    return ProbeResult(
        status=ProbeStatus.OK,
        duration_ms=int((time.monotonic() - started) * 1000),
        metrics=metrics,
    )
