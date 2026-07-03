"""MySQL 数据库采集（pymysql 直连 + show global status 解析）。"""
import time
from dataclasses import dataclass, asdict
from typing import Optional

import pymysql

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


_REQUIRED_FIELDS = ('host', 'port', 'user')


def _validate(params: dict) -> Optional[str]:
    """返回缺失字段名（首个），全部齐备返回 None。"""
    for f in _REQUIRED_FIELDS:
        if not params.get(f):
            return f
    return None


def probe_mysql(ds: DataSource, timeout_seconds: int = 5) -> ProbeResult:
    started = time.monotonic()
    # D-2b flat schema：从 ds.host/ds.port/ds.user/ds.password 组装 params
    params = {
        'host': ds.host,
        'port': ds.port or 3306,
        'user': ds.user,
        'password': ds.password or '',
        'database': '',
    }

    missing = _validate(params)
    if missing:
        return ProbeResult(
            status=ProbeStatus.MISCONFIGURED,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=f'凭据缺失字段：{missing}',
        )

    try:
        conn = pymysql.connect(
            host=params['host'],
            port=int(params.get('port', 3306)),
            user=params['user'],
            password=params.get('password', ''),
            database=params.get('database', ''),
            connect_timeout=timeout_seconds,
            read_timeout=timeout_seconds,
        )
    except (pymysql.OperationalError, pymysql.MySQLError, OSError) as exc:
        return ProbeResult(
            status=ProbeStatus.ERROR,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=f'MySQL 连接失败：{exc}',
        )

    try:
        cur = conn.cursor()
        cur.execute('SHOW GLOBAL STATUS')
        status_rows = cur.fetchall()
        status_map = {row[0]: row[1] for row in status_rows if len(row) >= 2}

        # 复制状态
        replication = {'is_slave': False, 'seconds_behind_master': None}
        try:
            dict_cur = conn.cursor(pymysql.cursors.DictCursor)
            dict_cur.execute('SHOW SLAVE STATUS')
            slave_dict = dict_cur.fetchone() or {}
            if slave_dict:
                replication['is_slave'] = True
                replication['seconds_behind_master'] = slave_dict.get('Seconds_Behind_Master')
            dict_cur.close()
        except (pymysql.MySQLError, AttributeError):
            pass

        # buffer pool hit rate
        read_req = int(status_map.get('Innodb_buffer_pool_read_requests', 0))
        read_miss = int(status_map.get('Innodb_buffer_pool_reads', 0))
        if read_req > 0:
            hit_rate = 1 - read_miss / read_req
        else:
            hit_rate = 1.0

        metrics = {
            'connections': int(status_map.get('Max_used_connections', 0)),
            'threads_connected': int(status_map.get('Threads_connected', 0)),
            'questions': int(status_map.get('Questions', 0)),
            'slow_queries': int(status_map.get('Slow_queries', 0)),
            'innodb_buffer_pool_hit_rate': round(hit_rate, 4),
            'replication': replication,
        }
        return ProbeResult(
            status=ProbeStatus.OK,
            duration_ms=int((time.monotonic() - started) * 1000),
            metrics=metrics,
        )
    finally:
        conn.close()