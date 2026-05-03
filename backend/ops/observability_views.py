from urllib.parse import quote

import json
import re

from django.conf import settings
from django.db.models import Count
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from eventwall.mixins import EventWallModelViewSetMixin
from eventwall.models import EventRecord
from eventwall.services import record_event
from rbac.permissions import RBACPermissionMixin, build_rbac_permission
from rbac.services import user_has_permissions
from .models import Alert, GrafanaSetting, LogDataSource, ObservabilityDataSourceLink, TracingDataSource
from .serializers import (
    AlertSerializer,
    GrafanaSettingSerializer,
    ObservabilityDataSourceLinkSerializer,
    TracingDataSourceSerializer,
)
from .tracing_providers import (
    DEMO_TRACES,
    ObservabilityError,
    load_trace_detail,
    load_tracing_catalog,
    search_tracing,
    test_tracing_connection,
    tracing_provider_info,
)


DEMO_GRAFANA_DASHBOARDS = [
    {'key': 'apm-overview', 'title': 'APM 全链路总览', 'slug': 'apm-overview', 'path': '/d/apm-overview', 'panel_count': 18, 'tags': ['SkyWalking', '应用', 'SLA'], 'description': '面向应用负责人查看服务吞吐、慢调用与错误率。'},
    {'key': 'infra-overview', 'title': '基础设施总览', 'slug': 'infra-overview', 'path': '/d/infra-overview', 'panel_count': 14, 'tags': ['Node', 'CPU', 'Memory'], 'description': '聚合节点 CPU、内存、磁盘与 Pod 负载走势。'},
    {'key': 'log-drilldown', 'title': '日志钻取看板', 'slug': 'log-drilldown', 'path': '/d/log-drilldown', 'panel_count': 12, 'tags': ['Loki', 'Error', 'Audit'], 'description': '配合日志中心快速回放错误时段与关键日志。'},
    {'key': 'ingress-slo', 'title': '入口流量与 SLO', 'slug': 'ingress-slo', 'path': '/d/ingress-slo', 'panel_count': 10, 'tags': ['Nginx', 'Latency', 'Availability'], 'description': '聚焦入口 QPS、响应时间分位和可用性目标。'},
    {'key': 'kubernetes-compute-resources-workload', 'title': 'Kubernetes / Compute Resources / Workload', 'slug': 'kubernetes-compute-resources-workload', 'path': '/d/k8s-resources-workload', 'panel_count': 16, 'tags': ['Kubernetes', 'Workload', 'Compute'], 'description': '按 namespace 和 workload 查看 Kubernetes 工作负载资源。'},
]


def _deny_if_missing_any(request, codes):
    allowed = any(user_has_permissions(request.user, [code]) for code in codes)
    if allowed:
        return None
    return Response({'detail': f"缺少权限: {', '.join(codes)}"}, status=403)


def _has_permission(request, code):
    return user_has_permissions(request.user, [code])


def _observability_access(request):
    return {
        'log_query': _has_permission(request, 'ops.log.query'),
        'log_datasource': _has_permission(request, 'ops.log.datasource.view'),
        'alerts': _has_permission(request, 'ops.alert.view'),
        'trace': _has_permission(request, 'ops.trace.view'),
        'trace_datasource': _has_permission(request, 'ops.trace.datasource.view'),
        'links': _has_permission(request, 'ops.observability.link.view'),
        'grafana': _has_permission(request, 'ops.grafana.view'),
    }


def _observability_defaults():
    return getattr(settings, 'OBSERVABILITY_CONFIG', {}) or {}


DEFAULT_TRACE_ID_FIELDS = ['trace_id', 'traceId', 'traceID', 'trace.id', 'otelTraceID']
DEFAULT_TRACE_ID_REGEX = re.compile(r'(?:"?(?:trace_id|traceId|traceID|trace\.id)"?\s*[:=]\s*"?(?P<trace>[0-9a-fA-F]{16,32})"?)')
DEFAULT_LOG_QUERY_TEMPLATE = '${__tags} | json | trace_id="${__trace.traceId}"'
DEFAULT_LOG_LABEL_MAPPINGS = [
    {'trace_tag': 'service.name', 'log_label': 'container'},
    {'trace_tag': 'service.namespace', 'log_label': 'namespace'},
]
DEFAULT_GRAFANA_VARIABLE_MAPPINGS = [
    {'trace_tag': 'service.name', 'variable': 'workload'},
    {'trace_tag': 'service.namespace', 'variable': 'namespace'},
]

SERVICE_TAG_ALIASES = [
    'service.name',
    'service',
    'service_name',
    'serviceName',
    'workload',
    'app',
    'application',
    'container',
    'container_name',
    'k8s.container.name',
    'kubernetes_container_name',
]
NAMESPACE_TAG_ALIASES = [
    'service.namespace',
    'namespace',
    'service_namespace',
    'serviceNamespace',
    'k8s.namespace.name',
    'kubernetes_namespace_name',
    'kubernetes.namespace',
]


def _normalize_trace_id_fields(values):
    fields = []
    for item in values or DEFAULT_TRACE_ID_FIELDS:
        text = str(item or '').strip()
        if text and text not in fields:
            fields.append(text)
    return fields


def _normalize_label_mappings(values):
    mappings = []
    for item in values or DEFAULT_LOG_LABEL_MAPPINGS:
        if not isinstance(item, dict):
            continue
        trace_tag = str(item.get('trace_tag') or '').strip()
        log_label = str(item.get('log_label') or '').strip()
        if trace_tag and log_label:
            mappings.append({'trace_tag': trace_tag, 'log_label': log_label})
    return mappings or list(DEFAULT_LOG_LABEL_MAPPINGS)


def _normalize_grafana_variable_mappings(values):
    mappings = []
    for item in values or DEFAULT_GRAFANA_VARIABLE_MAPPINGS:
        if not isinstance(item, dict):
            continue
        trace_tag = str(item.get('trace_tag') or '').strip()
        variable = str(item.get('variable') or '').strip()
        if trace_tag and variable:
            mappings.append({'trace_tag': trace_tag, 'variable': variable})
    return mappings or list(DEFAULT_GRAFANA_VARIABLE_MAPPINGS)


def _first_text_value(data, keys):
    if not isinstance(data, dict):
        return ''
    lowered = {str(key).lower().replace('_', '.'): value for key, value in data.items()}
    for key in keys:
        candidates = {
            key,
            key.replace('.', '_'),
            key.replace('_', '.'),
            key.lower(),
            key.lower().replace('_', '.'),
        }
        for candidate in candidates:
            value = data.get(candidate)
            if isinstance(value, str) and value.strip():
                return value.strip()
            lowered_value = lowered.get(candidate.lower().replace('_', '.'))
            if isinstance(lowered_value, str) and lowered_value.strip():
                return lowered_value.strip()
    return ''


def _merge_standard_trace_tags(tags):
    normalized = dict(tags or {})
    service = _first_text_value(normalized, SERVICE_TAG_ALIASES)
    namespace = _first_text_value(normalized, NAMESPACE_TAG_ALIASES)
    if service and not normalized.get('service.name'):
        normalized['service.name'] = service
    if namespace and not normalized.get('service.namespace'):
        normalized['service.namespace'] = namespace
    return normalized


def _trace_id_from_mapping(attributes, fields=None, message='', regex=''):
    fields = _normalize_trace_id_fields(fields)
    attributes = attributes or {}
    if isinstance(attributes, dict):
        for field in fields:
            for candidate in (field, field.replace('.', '_')):
                value = attributes.get(candidate)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for key, value in attributes.items():
            key_text = str(key).lower().replace('.', '_')
            if key_text in {'trace_id', 'traceid', 'oteltraceid'} and isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(message, str) and message.strip():
        try:
            parsed = json.loads(message)
            if isinstance(parsed, dict):
                nested = _trace_id_from_mapping(parsed, fields=fields, message='', regex=regex)
                if nested:
                    return nested
        except ValueError:
            pass
        pattern = DEFAULT_TRACE_ID_REGEX
        if regex:
            try:
                pattern = re.compile(regex)
            except re.error:
                pattern = DEFAULT_TRACE_ID_REGEX
        match = pattern.search(message)
        if match:
            return (match.groupdict().get('trace') or (match.group(1) if match.lastindex else match.group(0))).strip()
    return ''


def _render_log_selector(tags, mappings):
    tags = tags or {}
    mappings = _normalize_label_mappings(mappings)
    selector_parts = []
    for item in mappings:
        value = tags.get(item['trace_tag'])
        if isinstance(value, str) and value.strip():
            selector_parts.append(f'{item["log_label"]}="{value.strip()}"')
    return '{' + ','.join(selector_parts) + '}' if selector_parts else ''


def _render_log_query(link, trace_id, tags=None):
    template = (link.log_query_template or DEFAULT_LOG_QUERY_TEMPLATE).strip() or DEFAULT_LOG_QUERY_TEMPLATE
    selector = _render_log_selector(tags, link.log_label_mappings)
    query = template.replace('${__tags}', selector)
    query = query.replace('${__trace.traceId}', trace_id)
    query = query.replace('${__trace.traceID}', trace_id)
    query = query.replace('${__trace.id}', trace_id)
    query = query.replace('${traceId}', trace_id)
    if not trace_id:
        query = re.sub(r'\s*\|\s*(?:json\s*\|\s*)?trace_?id\s*=\s*""', '', query, flags=re.IGNORECASE)
    return query.strip()


def _resolve_observability_link(log_datasource_id='', tracing_datasource_id='', default_to_enabled=True):
    queryset = ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource').filter(is_enabled=True)
    has_filter = bool(log_datasource_id or tracing_datasource_id)
    if log_datasource_id:
        queryset = queryset.filter(log_datasource_id=log_datasource_id)
    if tracing_datasource_id:
        queryset = queryset.filter(tracing_datasource_id=tracing_datasource_id)
    link = queryset.order_by('-is_default', 'name').first()
    if link or has_filter or not default_to_enabled:
        return link
    return (
        ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource')
        .filter(is_enabled=True)
        .order_by('-is_default', 'name')
        .first()
    )


def _resolve_observability_link_for_dashboard(dashboard_key=''):
    key = str(dashboard_key or '').strip()
    queryset = ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource').filter(is_enabled=True)
    if key:
        exact = queryset.filter(grafana_dashboard_key__iexact=key).order_by('-is_default', 'name').first()
        if exact:
            return exact
    return queryset.order_by('-is_default', 'name').first()


def _link_payload(link):
    data = ObservabilityDataSourceLinkSerializer(link).data
    data['trace_id_fields'] = data.get('trace_id_fields') or DEFAULT_TRACE_ID_FIELDS
    data['trace_id_regex'] = data.get('trace_id_regex') or DEFAULT_TRACE_ID_REGEX.pattern
    data['log_query_template'] = data.get('log_query_template') or DEFAULT_LOG_QUERY_TEMPLATE
    data['log_label_mappings'] = data.get('log_label_mappings') or DEFAULT_LOG_LABEL_MAPPINGS
    data['grafana_variable_mappings'] = data.get('grafana_variable_mappings') or DEFAULT_GRAFANA_VARIABLE_MAPPINGS
    return data


def _find_grafana_dashboard(dashboard_key=''):
    grafana = _grafana_meta()
    dashboards = grafana.get('dashboards') or []
    key = str(dashboard_key or '').strip()
    if key:
        normalized_key = key.lower()
        for dashboard in dashboards:
            candidates = [
                dashboard.get('key'),
                dashboard.get('slug'),
                dashboard.get('title'),
            ]
            if any(str(candidate or '').strip().lower() == normalized_key for candidate in candidates):
                return grafana, dashboard
    for dashboard in dashboards:
        tags = {str(tag).lower() for tag in dashboard.get('tags') or []}
        title = str(dashboard.get('title') or '').lower()
        if 'apm' in tags or '应用' in tags or 'trace' in tags or '链路' in title or 'apm' in title:
            return grafana, dashboard
    return grafana, dashboards[0] if dashboards else {}


def _render_grafana_query(link, trace_id, tags=None):
    tags = _merge_standard_trace_tags(tags or {})
    query = {'traceId': trace_id}
    service = tags.get('service.name') or tags.get('service') or ''
    if isinstance(service, str) and service.strip():
        query['service'] = service.strip()
    for item in _normalize_grafana_variable_mappings(link.grafana_variable_mappings):
        value = tags.get(item['trace_tag'])
        if isinstance(value, str) and value.strip():
            query[f'var-{item["variable"]}'] = value.strip()
    return query


def _dashboard_context_from_request(data):
    context = {}
    for key, value in (data or {}).items():
        if key in {'dashboard_key', 'dashboard', 'log_datasource_id', 'tracing_datasource_id', 'datasource_id'}:
            continue
        if isinstance(value, str) and value.strip():
            context[key] = value.strip()
        elif isinstance(value, (int, float)):
            context[key] = value
    raw_query = data.get('query') if isinstance(data, dict) else {}
    if isinstance(raw_query, dict):
        for key, value in raw_query.items():
            if isinstance(value, str) and value.strip():
                context[key] = value.strip()
            elif isinstance(value, (int, float)):
                context[key] = value
    return context


def _tags_from_grafana_context(link, context):
    tags = {}
    context = context or {}
    for item in _normalize_grafana_variable_mappings(link.grafana_variable_mappings):
        value = context.get(f'var-{item["variable"]}') or context.get(item['variable'])
        if isinstance(value, str) and value.strip():
            tags[item['trace_tag']] = value.strip()
    service = context.get('service') or context.get('var-service') or context.get('workload') or context.get('var-workload')
    namespace = context.get('namespace') or context.get('var-namespace')
    if isinstance(service, str) and service.strip() and not tags.get('service.name'):
        tags['service.name'] = service.strip()
    if isinstance(namespace, str) and namespace.strip() and not tags.get('service.namespace'):
        tags['service.namespace'] = namespace.strip()
    return _merge_standard_trace_tags(tags)


def _tags_from_log_attributes(link, attributes):
    tags = dict(attributes or {})
    for item in _normalize_label_mappings(link.log_label_mappings):
        value = attributes.get(item['log_label']) if isinstance(attributes, dict) else ''
        if isinstance(value, str) and value.strip() and not tags.get(item['trace_tag']):
            tags[item['trace_tag']] = value.strip()
    return _merge_standard_trace_tags(tags)


def _grafana_resolve_payload(link, trace_id, tags=None, request_data=None):
    request_data = request_data or {}
    dashboard_hint = request_data.get('dashboard_key') or request_data.get('dashboard') or request_data.get('grafana_dashboard_key') or link.grafana_dashboard_key
    grafana, dashboard = _find_grafana_dashboard(dashboard_hint)
    if not dashboard:
        return None
    dashboard_key = dashboard.get('key') or dashboard.get('slug') or link.grafana_dashboard_key
    query = _render_grafana_query(link, trace_id, tags=tags)
    query.update({
        'dashboard': dashboard_key,
        'source': 'trace',
    })
    if request_data.get('from'):
        query['from'] = request_data.get('from')
    if request_data.get('to'):
        query['to'] = request_data.get('to')
    return {
        'link': _link_payload(link),
        'trace_id': trace_id,
        'grafana': {
            'configured': grafana.get('configured'),
            'url': grafana.get('url'),
        },
        'dashboard': dashboard,
        'query': query,
    }


def _join_external_url(base, path=''):
    base = (base or '').rstrip('/')
    if not base:
        return ''
    normalized_path = (path or '').strip()
    if not normalized_path:
        return base
    if not normalized_path.startswith('/'):
        normalized_path = f'/{normalized_path}'
    return f'{base}{normalized_path}'


def _grafana_config():
    config = dict(_observability_defaults().get('grafana', {}))
    config.setdefault('enabled', True)
    config.setdefault('url', '')
    config.setdefault('default_path', '')
    config.setdefault('demo_mode', True)
    config.setdefault('folders', [])
    config.setdefault('dashboards', [])
    db_config = _get_grafana_setting()
    if db_config:
        config.update({
            'enabled': db_config.enabled,
            'url': db_config.url,
            'default_path': db_config.default_path,
            'folders': db_config.folders or config.get('folders') or [],
            'dashboards': db_config.dashboards or config.get('dashboards') or [],
        })
    return config


def _get_grafana_setting():
    return GrafanaSetting.objects.filter(name='default').first()


def _grafana_meta():
    config = _grafana_config()
    configured_dashboards = config.get('dashboards') or DEMO_GRAFANA_DASHBOARDS
    configured_folders = config.get('folders') or []
    dashboards = []
    base_url = config.get('url') or ''
    default_path = (config.get('default_path') or '').strip()
    for item in configured_dashboards:
        full_url = (item.get('full_url') or item.get('url') or '').strip()
        item_path = (item.get('path') or '').strip()
        slug = item.get('slug') or item.get('key') or ''
        path = item_path or default_path or (f"/d/{quote(slug)}" if slug else '')
        resolved_url = full_url or (_join_external_url(base_url, path) if base_url and path else base_url)
        dashboards.append({
            **item,
            'path': path,
            'full_url': full_url,
            'url': resolved_url,
        })
    has_dashboard_url = any(item.get('url') for item in dashboards)
    configured = bool(config.get('enabled') and (base_url or has_dashboard_url))
    return {
        'enabled': bool(config.get('enabled')),
        'configured': configured,
        'source': 'grafana' if configured else 'demo',
        'status_text': '已接入 Grafana' if configured else '未配置外部地址，当前展示推荐看板',
        'url': base_url,
        'embed_url': _join_external_url(base_url, default_path) if base_url and default_path else (dashboards[0]['url'] if dashboards else base_url),
        'dashboard_count': len(dashboards),
        'panel_count': sum(item['panel_count'] for item in dashboards),
        'datasource_count': 4,
        'folders': configured_folders,
        'dashboards': dashboards,
    }


def _log_module_summary():
    providers = []
    grouped = LogDataSource.objects.values('provider').annotate(total=Count('id')).order_by('provider')
    enabled_by_provider = {
        item['provider']: item['count']
        for item in LogDataSource.objects.filter(is_enabled=True).values('provider').annotate(count=Count('id'))
    }
    for item in grouped:
        provider = item['provider']
        providers.append({
            'provider': provider,
            'total': item['total'],
            'enabled': enabled_by_provider.get(provider, 0),
        })

    return {
        'query_path': '/logs/query',
        'datasource_path': '/logs/datasources',
        'datasource_count': LogDataSource.objects.count(),
        'enabled_count': LogDataSource.objects.filter(is_enabled=True).count(),
        'default_count': LogDataSource.objects.filter(is_default=True).count(),
        'providers': providers,
    }


def _alert_module_summary():
    latest = Alert.objects.select_related('host').all()[:5]
    return {
        'path': '/alerts',
        'total': Alert.objects.count(),
        'unacknowledged': Alert.objects.filter(is_acknowledged=False).count(),
        'critical': Alert.objects.filter(level='critical').count(),
        'warning': Alert.objects.filter(level='warning').count(),
        'info': Alert.objects.filter(level='info').count(),
        'recent': AlertSerializer(latest, many=True).data,
    }


class ObservabilityDataSourceLinkViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = ObservabilityDataSourceLink.objects.select_related('log_datasource', 'tracing_datasource').all()
    serializer_class = ObservabilityDataSourceLinkSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'observability_datasource_link'
    event_resource_label = '可观测数据源关联'
    event_resource_name_fields = ('name',)
    demo_account_allowed_actions = {'resolve_trace_to_logs', 'resolve_log_to_trace', 'resolve_trace_to_grafana', 'resolve_log_to_grafana', 'resolve_grafana_to_logs', 'resolve_grafana_to_trace'}
    rbac_permissions = {
        'list': ['ops.observability.link.view'],
        'retrieve': ['ops.observability.link.view'],
        'create': ['ops.observability.link.manage'],
        'update': ['ops.observability.link.manage'],
        'partial_update': ['ops.observability.link.manage'],
        'destroy': ['ops.observability.link.manage'],
        'resolve_trace_to_logs': ['ops.observability.link.view', 'ops.log.query'],
        'resolve_log_to_trace': ['ops.observability.link.view', 'ops.trace.view'],
        'resolve_trace_to_grafana': ['ops.observability.link.view', 'ops.grafana.view'],
        'resolve_log_to_grafana': ['ops.observability.link.view', 'ops.grafana.view'],
        'resolve_grafana_to_logs': ['ops.observability.link.view', 'ops.log.query'],
        'resolve_grafana_to_trace': ['ops.observability.link.view', 'ops.trace.view'],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        log_datasource_id = self.request.query_params.get('log_datasource_id')
        tracing_datasource_id = self.request.query_params.get('tracing_datasource_id')
        is_enabled = self.request.query_params.get('is_enabled')
        if log_datasource_id:
            queryset = queryset.filter(log_datasource_id=log_datasource_id)
        if tracing_datasource_id:
            queryset = queryset.filter(tracing_datasource_id=tracing_datasource_id)
        if is_enabled in ('true', 'false'):
            queryset = queryset.filter(is_enabled=is_enabled == 'true')
        return queryset.order_by('-is_default', 'name')

    @action(detail=False, methods=['post'])
    def resolve_trace_to_logs(self, request):
        trace_id = str(request.data.get('trace_id') or '').strip()
        if not trace_id:
            return Response({'detail': '缺少 trace_id'}, status=status.HTTP_400_BAD_REQUEST)
        link = _resolve_observability_link(
            tracing_datasource_id=request.data.get('tracing_datasource_id') or request.data.get('datasource_id') or '',
        )
        if not link or not link.trace_to_log_enabled:
            return Response({'detail': '未找到可用的链路到日志数据源关联'}, status=status.HTTP_404_NOT_FOUND)
        tags = request.data.get('tags') if isinstance(request.data.get('tags'), dict) else {}
        query = _render_log_query(link, trace_id, tags=tags)
        return Response({
            'link': _link_payload(link),
            'trace_id': trace_id,
            'log_datasource': {
                'id': link.log_datasource_id,
                'name': link.log_datasource.name,
                'provider': link.log_datasource.provider,
            },
            'query': query,
            'source': link.log_datasource.name,
            'window_minutes': link.window_minutes,
            'span_start_shift': link.span_start_shift,
            'span_end_shift': link.span_end_shift,
        })

    @action(detail=False, methods=['post'])
    def resolve_log_to_trace(self, request):
        link = _resolve_observability_link(
            log_datasource_id=request.data.get('log_datasource_id') or request.data.get('datasource_id') or '',
        )
        if not link or not link.log_to_trace_enabled:
            return Response({'detail': '未找到可用的日志到链路数据源关联'}, status=status.HTTP_404_NOT_FOUND)

        attributes = request.data.get('attributes') if isinstance(request.data.get('attributes'), dict) else {}
        message = request.data.get('message') or ''
        trace_id = (
            str(request.data.get('trace_id') or '').strip()
            or _trace_id_from_mapping(attributes, fields=link.trace_id_fields, message=message, regex=link.trace_id_regex)
        )
        if not trace_id:
            return Response({'detail': '未能从日志内容中解析 Trace ID'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'link': _link_payload(link),
            'trace_id': trace_id,
            'tracing_datasource': {
                'id': link.tracing_datasource_id,
                'name': link.tracing_datasource.name,
                'provider': link.tracing_datasource.provider,
            },
        })

    @action(detail=False, methods=['post'])
    def resolve_trace_to_grafana(self, request):
        trace_id = str(request.data.get('trace_id') or '').strip()
        if not trace_id:
            return Response({'detail': '缺少 trace_id'}, status=status.HTTP_400_BAD_REQUEST)
        link = _resolve_observability_link(
            tracing_datasource_id=request.data.get('tracing_datasource_id') or request.data.get('datasource_id') or '',
        )
        if not link or not link.trace_to_grafana_enabled:
            return Response({'detail': '未找到可用的链路到 Grafana 看板关联'}, status=status.HTTP_404_NOT_FOUND)
        tags = request.data.get('tags') if isinstance(request.data.get('tags'), dict) else {}
        payload = _grafana_resolve_payload(link, trace_id, tags=tags, request_data=request.data)
        if not payload:
            return Response({'detail': '未找到可用的 Grafana 看板配置'}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)

    @action(detail=False, methods=['post'])
    def resolve_log_to_grafana(self, request):
        link = _resolve_observability_link(
            log_datasource_id=request.data.get('log_datasource_id') or request.data.get('datasource_id') or '',
        )
        if not link or not link.log_to_grafana_enabled:
            return Response({'detail': '未找到可用的日志到 Grafana 看板关联'}, status=status.HTTP_404_NOT_FOUND)

        attributes = request.data.get('attributes') if isinstance(request.data.get('attributes'), dict) else {}
        message = request.data.get('message') or ''
        trace_id = (
            str(request.data.get('trace_id') or '').strip()
            or _trace_id_from_mapping(attributes, fields=link.trace_id_fields, message=message, regex=link.trace_id_regex)
        )
        if not trace_id:
            return Response({'detail': '未能从日志内容中解析 Trace ID'}, status=status.HTTP_400_BAD_REQUEST)
        tags = _tags_from_log_attributes(link, attributes)
        payload = _grafana_resolve_payload(link, trace_id, tags=tags, request_data=request.data)
        if not payload:
            return Response({'detail': '未找到可用的 Grafana 看板配置'}, status=status.HTTP_404_NOT_FOUND)
        payload['query']['source'] = 'log'
        return Response(payload)

    @action(detail=False, methods=['post'])
    def resolve_grafana_to_logs(self, request):
        dashboard_key = request.data.get('dashboard_key') or request.data.get('dashboard') or request.data.get('grafana_dashboard_key') or ''
        link = _resolve_observability_link_for_dashboard(dashboard_key)
        if not link or not link.grafana_to_log_enabled:
            return Response({'detail': '未找到可用的 Grafana 看板到日志关联'}, status=status.HTTP_404_NOT_FOUND)
        context = _dashboard_context_from_request(request.data)
        tags = _tags_from_grafana_context(link, context)
        if not tags:
            return Response({'detail': '看板上下文缺少可用于日志查询的变量'}, status=status.HTTP_400_BAD_REQUEST)
        trace_id = str(context.get('traceId') or context.get('trace_id') or '').strip()
        query = _render_log_query(link, trace_id, tags=tags)
        if not query:
            return Response({'detail': '看板上下文缺少可用于日志查询的变量'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'link': _link_payload(link),
            'dashboard_key': dashboard_key,
            'trace_id': trace_id,
            'tags': tags,
            'log_datasource': {
                'id': link.log_datasource_id,
                'name': link.log_datasource.name,
                'provider': link.log_datasource.provider,
            },
            'query': query,
            'window_minutes': link.window_minutes,
        })

    @action(detail=False, methods=['post'])
    def resolve_grafana_to_trace(self, request):
        dashboard_key = request.data.get('dashboard_key') or request.data.get('dashboard') or request.data.get('grafana_dashboard_key') or ''
        link = _resolve_observability_link_for_dashboard(dashboard_key)
        if not link or not link.grafana_to_trace_enabled:
            return Response({'detail': '未找到可用的 Grafana 看板到链路关联'}, status=status.HTTP_404_NOT_FOUND)
        context = _dashboard_context_from_request(request.data)
        tags = _tags_from_grafana_context(link, context)
        service = tags.get('service.name') or context.get('service') or context.get('var-service') or ''
        trace_id = str(context.get('traceId') or context.get('trace_id') or '').strip()
        return Response({
            'link': _link_payload(link),
            'dashboard_key': dashboard_key,
            'trace_id': trace_id,
            'tags': tags,
            'service': service,
            'tracing_datasource': {
                'id': link.tracing_datasource_id,
                'name': link.tracing_datasource.name,
                'provider': link.tracing_datasource.provider,
            },
            'window_minutes': link.window_minutes,
        })


class TracingDataSourceViewSet(EventWallModelViewSetMixin, RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = TracingDataSource.objects.all().order_by('provider', 'name')
    serializer_class = TracingDataSourceSerializer
    pagination_class = None
    event_module = 'ops'
    event_resource_type = 'tracing_datasource'
    event_resource_label = '链路数据源'
    event_resource_name_fields = ('name',)
    event_exclude_fields = ('config',)
    rbac_permissions = {
        'list': ['ops.trace.datasource.view'],
        'retrieve': ['ops.trace.datasource.view'],
        'create': ['ops.trace.datasource.manage'],
        'update': ['ops.trace.datasource.manage'],
        'partial_update': ['ops.trace.datasource.manage'],
        'destroy': ['ops.trace.datasource.manage'],
        'test_connection': ['ops.trace.datasource.manage'],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        provider = self.request.query_params.get('provider')
        is_enabled = self.request.query_params.get('is_enabled')
        if provider:
            queryset = queryset.filter(provider=provider)
        if is_enabled in ('true', 'false'):
            queryset = queryset.filter(is_enabled=is_enabled == 'true')
        return queryset

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        datasource = self.get_object()
        try:
            preview = test_tracing_connection(datasource.provider, datasource.config or {})
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_tracing_datasource',
                title='测试链路数据源连通性',
                summary=f'链路数据源 {datasource.name} 连通性测试成功',
                resource_type='tracing_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'tracing-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'preview_kind': preview.get('kind'), 'count': preview.get('count', 0)},
            )
            return Response({
                'success': True,
                'message': f'{datasource.name} 连接成功',
                'preview_count': preview.get('count', 0),
                'preview_kind': preview.get('kind'),
            })
        except ObservabilityError as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_tracing_datasource',
                title='测试链路数据源连通性',
                summary=f'链路数据源 {datasource.name} 连通性测试失败',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='tracing_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'tracing-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'error': str(exc)},
            )
            return Response({'success': False, 'message': str(exc), 'detail': exc.detail}, status=exc.status_code)
        except Exception as exc:
            record_event(
                request=request,
                module='ops',
                category='execution',
                action='test_tracing_datasource',
                title='测试链路数据源连通性',
                summary=f'链路数据源 {datasource.name} 连通性测试失败',
                result=EventRecord.RESULT_FAILED,
                severity=EventRecord.SEVERITY_WARNING,
                resource_type='tracing_datasource',
                resource_id=datasource.id,
                resource_name=datasource.name,
                correlation_id=f'tracing-datasource:{datasource.id}',
                metadata={'provider': datasource.provider, 'error': str(exc)},
            )
            return Response(
                {'success': False, 'message': '连接测试失败', 'detail': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.trace.datasource.view')])
def tracing_providers(request):
    return Response({'providers': tracing_provider_info()})


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.grafana.view')])
def grafana_setting_view(request):
    instance = _get_grafana_setting()
    if request.method == 'GET':
        config = _grafana_config()
        payload = {
            'id': instance.id if instance else None,
            'name': instance.name if instance else 'default',
            'enabled': bool(config.get('enabled')),
            'url': config.get('url') or '',
            'default_path': config.get('default_path') or '',
            'folders': config.get('folders') or [],
            'dashboards': config.get('dashboards') or DEMO_GRAFANA_DASHBOARDS,
            'updated_by': instance.updated_by if instance else '',
            'created_at': instance.created_at if instance else None,
            'updated_at': instance.updated_at if instance else None,
            'persisted': bool(instance),
        }
        return Response(payload)

    if not user_has_permissions(request.user, ['ops.grafana.manage']):
        return Response({'detail': '缺少 ops.grafana.manage 权限'}, status=status.HTTP_403_FORBIDDEN)

    if instance is None:
        instance = GrafanaSetting(name='default')
    serializer = GrafanaSettingSerializer(instance=instance, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    saved = serializer.save(updated_by=request.user.username)
    record_event(
        request=request,
        module='ops',
        category='configuration',
        action='update_grafana_setting',
        title='更新 Grafana 配置',
        summary='已更新监控看板接入配置',
        resource_type='grafana_setting',
        resource_id=saved.id,
        resource_name=saved.name,
        correlation_id=f'grafana-setting:{saved.id}',
        metadata={'url': saved.url, 'enabled': saved.enabled, 'default_path': saved.default_path},
    )
    response_data = GrafanaSettingSerializer(saved).data
    response_data['persisted'] = True
    return Response(response_data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_overview(request):
    access = _observability_access(request)
    denied = _deny_if_missing_any(
        request,
        ['ops.log.query', 'ops.log.datasource.view', 'ops.alert.view', 'ops.trace.view', 'ops.trace.datasource.view', 'ops.observability.link.view', 'ops.grafana.view'],
    )
    if denied:
        return denied

    provider = request.query_params.get('provider', '')
    layer = request.query_params.get('layer', '')
    try:
        catalog = load_tracing_catalog(
            provider=provider,
            layer=layer,
            datasource_id=request.query_params.get('datasource_id', ''),
        ) if access['trace'] else None
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)
    grafana = _grafana_meta() if access['grafana'] else None
    logs = _log_module_summary() if (access['log_query'] or access['log_datasource']) else None
    alerts = _alert_module_summary() if access['alerts'] else None

    navigation = []
    if access['log_query'] or access['log_datasource']:
        log_description = '统一进入日志查询与数据源管理。' if access['log_query'] and access['log_datasource'] else '进入日志中心并按当前权限查看可用标签。'
        navigation.append({'title': '日志中心', 'path': '/logs', 'description': log_description, 'tone': 'info'})
    if access['alerts']:
        navigation.append({'title': '告警中心', 'path': '/alerts', 'description': '集中处理当前未确认和高优先级告警。', 'tone': 'danger'})
    if access['trace']:
        navigation.append({'title': '链路追踪', 'path': '/observability/tracing', 'description': '统一查看 SkyWalking 与 OpenTelemetry Trace、Span 和调用拓扑。', 'tone': 'success'})
    if access['trace_datasource']:
        navigation.append({'title': '链路数据源', 'path': '/observability/tracing/datasources', 'description': '维护 SkyWalking、Tempo、Jaeger、Zipkin 查询入口与默认数据源。', 'tone': 'warning'})
    if access['grafana']:
        navigation.append({'title': 'Grafana 大屏', 'path': '/observability/grafana', 'description': '打开监控看板和推荐大屏。', 'tone': 'accent'})

    return Response({
        'modules': {
            'tracing': catalog['tracing'] if catalog else None,
            'grafana': grafana,
            'logs': logs,
            'alerts': alerts,
        },
        'summary': {
            'service_count': catalog['summary']['service_count'] if catalog else 0,
            'trace_count': catalog['summary']['trace_count'] if catalog else 0,
            'error_count': catalog['summary']['error_count'] if catalog else 0,
            'topology_nodes': catalog['summary']['topology_nodes'] if catalog else 0,
            'dashboard_count': grafana['dashboard_count'] if grafana else 0,
            'datasource_count': logs['datasource_count'] if logs else 0,
            'unacknowledged_alerts': alerts['unacknowledged'] if alerts else 0,
        },
        'navigation': navigation,
        'recent_traces': catalog['recent_traces'] if catalog else [],
        'providers': catalog['providers'] if catalog else [
            {
                'provider': item['id'],
                'provider_name': item['name'],
                'source': 'demo' if not item['configured'] else item['id'],
                'configured': item['configured'],
                'active': False,
            }
            for item in (tracing_provider_info() if access['trace_datasource'] else [])
        ],
        'recent_alerts': alerts['recent'] if alerts else [],
        'tips': [
            '链路追踪优先接入 SkyWalking、Tempo、Jaeger 或 Zipkin；未配置时自动展示演示数据。',
            'Tempo、Jaeger、Zipkin 统一按 OpenTelemetry 风格归一化为标准 Trace / Span 模型。',
            '日志中心、告警中心与链路追踪已收敛到可观测性菜单，便于统一排障。',
        ],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_tracing_catalog(request):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    try:
        return Response(load_tracing_catalog(
            provider=request.query_params.get('provider', ''),
            layer=request.query_params.get('layer', ''),
            datasource_id=request.query_params.get('datasource_id', ''),
            service_id=request.query_params.get('service_id', ''),
        ))
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def observability_tracing_search(request):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    try:
        return Response(search_tracing(request.data or {}))
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def observability_trace_detail(request, trace_id):
    denied = _deny_if_missing_any(request, ['ops.trace.view'])
    if denied:
        return denied
    try:
        return Response(load_trace_detail(
            trace_id,
            provider=request.query_params.get('provider', ''),
            layer=request.query_params.get('layer', ''),
            datasource_id=request.query_params.get('datasource_id', ''),
        ))
    except ObservabilityError as exc:
        return Response({'detail': str(exc), 'error': exc.detail}, status=exc.status_code)
