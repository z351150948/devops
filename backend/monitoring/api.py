"""监控 APIView — on-demand 采集入口。"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied

from rbac.permissions import user_has_permissions
from rbac.registry import PERMISSION_DEFINITIONS  # noqa: 避免循环 import

from ops.models import Host
from sqlaudit.models import DataSource
from monitoring.services.host_probe import probe_host, ProbeResult
from monitoring.services.mysql_probe import probe_mysql
# D-2b：redis_probe 不再 import（api.py 不再分发 redis 分支）
from monitoring.services.mongo_probe import probe_mongo
from monitoring.models import ProbeAudit


def _audit_save(target_kind: str, target_id: int, result: ProbeResult):
    """更新最近一次采集状态（不写 EventWall）。"""
    ProbeAudit.objects.update_or_create(
        target_kind=target_kind,
        target_id=target_id,
        defaults={
            'last_status': result.status,
            'last_error': result.error or '',
            'last_duration_ms': result.duration_ms,
        },
    )


def _bulk_host_probe(hosts, timeout_seconds: int = 5, max_workers: int = 8) -> list:
    """对 hosts 列表并发执行 SSH 采集，单 host 失败不中断其他。"""
    results = [None] * len(hosts)
    if not hosts:
        return results
    if len(hosts) <= 16:
        workers = min(max_workers, len(hosts))
    else:
        workers = max_workers

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {pool.submit(probe_host, h, timeout_seconds): i for i, h in enumerate(hosts)}
        for fut in as_completed(future_to_idx):
            i = future_to_idx[fut]
            try:
                results[i] = fut.result()
            except Exception as exc:  # noqa: 兜底任何未捕获异常
                from monitoring.services.host_probe import ProbeResult, ProbeStatus
                results[i] = ProbeResult(
                    status=ProbeStatus.ERROR,
                    duration_ms=0,
                    metrics=None,
                    error=f'未捕获异常：{exc}',
                )
    return results


def _bulk_database_probe(ds_list, timeout_seconds: int = 5) -> list:
    """对 data sources 顺序采集（DB 探针本身不应并发，D-2b：仅 mysql/mongodb）。"""
    results = []
    for ds in ds_list:
        if ds.db_type == 'mysql' or ds.db_type == 'polardb':
            # PolarDB 走 MySQL service 路径（pymysql 兼容）
            r = probe_mysql(ds, timeout_seconds)
        elif ds.db_type == 'mongodb':
            r = probe_mongo(ds, timeout_seconds)
        else:
            from monitoring.services.mysql_probe import ProbeResult, ProbeStatus
            # db_type 可能是 'redis'（不存在，状态 misconfigured）或其他未知
            r = ProbeResult(
                status=ProbeStatus.MISCONFIGURED,
                duration_ms=0,
                metrics=None,
                error=f'不支持的 db_type：{ds.db_type}（D-2b 降级：仅支持 mysql/mongodb/polardb）',
            )
        results.append(r)
    return results


class HostProbeBulkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not user_has_permissions(request.user, ['monitoring.host.view']):
            raise PermissionDenied('无 monitoring.host.view 权限')

        ids = request.data.get('ids', []) if isinstance(request.data, dict) else []
        if ids:
            hosts = list(Host.objects.filter(pk__in=ids))
        else:
            hosts = list(Host.objects.all())
        # 按 ids 顺序补全（保序，未匹配 id 不出现）
        host_map = {h.id: h for h in hosts}

        started = time.monotonic()
        results = _bulk_host_probe(hosts)
        total_ms = int((time.monotonic() - started) * 1000)

        items = []
        for i, host in enumerate(hosts):
            r = results[i]
            _audit_save(ProbeAudit.TARGET_HOST, host.id, r)
            items.append({
                'id': host.id,
                'hostname': host.hostname,
                'ip': host.ip_address,
                'status': r.status,
                'duration_ms': r.duration_ms,
                'metrics': r.metrics,
                'error': r.error,
            })

        return Response({
            'results': items,
            'summary': {
                'total': len(items),
                'ok': sum(1 for it in items if it['status'] == 'ok'),
                'error': sum(1 for it in items if it['status'] == 'error'),
                'timeout': sum(1 for it in items if it['status'] == 'timeout'),
                'duration_ms': total_ms,
            },
        })


class HostProbeSingleView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, host_id):
        if not user_has_permissions(request.user, ['monitoring.host.view']):
            raise PermissionDenied('无 monitoring.host.view 权限')

        try:
            host = Host.objects.get(pk=host_id)
        except Host.DoesNotExist:
            return Response({'detail': 'host not found'}, status=status.HTTP_404_NOT_FOUND)

        result = probe_host(host, timeout_seconds=5)
        _audit_save(ProbeAudit.TARGET_HOST, host.id, result)
        return Response({
            'id': host.id,
            'hostname': host.hostname,
            'ip': host.ip_address,
            'status': result.status,
            'duration_ms': result.duration_ms,
            'metrics': result.metrics,
            'error': result.error,
        })


class DatabaseProbeBulkView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not user_has_permissions(request.user, ['monitoring.database.view']):
            raise PermissionDenied('无 monitoring.database.view 权限')

        ids = request.data.get('ids', []) if isinstance(request.data, dict) else []
        if ids:
            ds_list = list(DataSource.objects.filter(pk__in=ids))
        else:
            ds_list = list(DataSource.objects.all())

        started = time.monotonic()
        results = _bulk_database_probe(ds_list)
        total_ms = int((time.monotonic() - started) * 1000)

        items = []
        for ds, r in zip(ds_list, results):
            _audit_save(ProbeAudit.TARGET_DATABASE, ds.id, r)
            # D-2b flat schema：ds.host / ds.port，不存在 connection_params
            items.append({
                'id': ds.id,
                'name': ds.name,
                'type': ds.db_type,
                'host': ds.host,
                'port': ds.port or None,
                'status': r.status,
                'duration_ms': r.duration_ms,
                'metrics': r.metrics,
                'error': r.error,
            })

        return Response({
            'results': items,
            'summary': {
                'total': len(items),
                'ok': sum(1 for it in items if it['status'] == 'ok'),
                'error': sum(1 for it in items if it['status'] == 'error'),
                'timeout': sum(1 for it in items if it['status'] == 'timeout'),
                'duration_ms': total_ms,
            },
        })


class DatabaseProbeSingleView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ds_id):
        if not user_has_permissions(request.user, ['monitoring.database.view']):
            raise PermissionDenied('无 monitoring.database.view 权限')

        try:
            ds = DataSource.objects.get(pk=ds_id)
        except DataSource.DoesNotExist:
            return Response({'detail': 'datasource not found'}, status=status.HTTP_404_NOT_FOUND)

        if ds.db_type == 'mysql' or ds.db_type == 'polardb':
            r = probe_mysql(ds, timeout_seconds=5)
        elif ds.db_type == 'mongodb':
            r = probe_mongo(ds, timeout_seconds=5)
        else:
            from monitoring.services.mysql_probe import ProbeResult, ProbeStatus
            r = ProbeResult(
                status=ProbeStatus.MISCONFIGURED,
                duration_ms=0,
                metrics=None,
                error=f'不支持的 db_type：{ds.db_type}（D-2b 降级：仅支持 mysql/mongodb/polardb）',
            )
        _audit_save(ProbeAudit.TARGET_DATABASE, ds.id, r)
        return Response({
            'id': ds.id,
            'name': ds.name,
            'type': ds.db_type,
            'host': ds.host,           # D-2b：flat 字段
            'port': ds.port or None,   # D-2b：flat 字段
            'status': r.status,
            'duration_ms': r.duration_ms,
            'metrics': r.metrics,
            'error': r.error,
        })
