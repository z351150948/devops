from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from rbac.permissions import RBACPermissionMixin

from .models import EventRecord
from .serializers import EventRecordSerializer


DEMO_WINDOW_MINUTES = 7 * 24 * 60 - 1


def _refresh_demo_event_timestamps():
    now = timezone.localtime().replace(second=0, microsecond=0)
    changed = []
    for item in EventRecord.objects.filter(is_demo=True).only('id', 'occurred_at', 'metadata'):
        metadata = item.metadata or {}
        offset = metadata.get('demo_offset_minutes')
        if offset is None:
            continue
        try:
            offset_minutes = max(0, min(int(offset), DEMO_WINDOW_MINUTES))
        except (TypeError, ValueError):
            continue
        target = now - timedelta(minutes=offset_minutes)
        if item.occurred_at != target:
            item.occurred_at = target
            changed.append(item)
    if changed:
        EventRecord.objects.bulk_update(changed, ['occurred_at'])


def _parse_time_range(params):
    start_at = params.get('start_at', '').strip()
    end_at = params.get('end_at', '').strip()
    start = parse_datetime(start_at) if start_at else None
    end = parse_datetime(end_at) if end_at else None
    if start and timezone.is_naive(start):
        start = timezone.make_aware(start, timezone.get_current_timezone())
    if end and timezone.is_naive(end):
        end = timezone.make_aware(end, timezone.get_current_timezone())
    return start, end


def _build_window(queryset, params, default_days=7):
    start, end = _parse_time_range(params)
    if start:
        queryset = queryset.filter(occurred_at__gte=start)
    if end:
        queryset = queryset.filter(occurred_at__lte=end)
    if start or end:
        return queryset, start, end

    days = params.get('days', '').strip()
    if days.isdigit():
        start = timezone.now() - timedelta(days=int(days))
        return queryset.filter(occurred_at__gte=start), start, None

    if default_days is not None:
        start = timezone.now() - timedelta(days=default_days)
        return queryset.filter(occurred_at__gte=start), start, None

    return queryset, None, None


class EventRecordViewSet(RBACPermissionMixin, viewsets.ReadOnlyModelViewSet):
    queryset = EventRecord.objects.select_related('parent_event').all()
    serializer_class = EventRecordSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = [
        'title',
        'summary',
        'detail',
        'actor_username',
        'resource_name',
        'resource_type',
        'correlation_id',
    ]
    rbac_permissions = {
        'list': ['eventwall.view'],
        'retrieve': ['eventwall.view'],
        'overview': ['eventwall.view'],
        'associations': ['eventwall.view'],
        'filter_options': ['eventwall.view'],
    }

    def get_queryset(self):
        _refresh_demo_event_timestamps()
        queryset = super().get_queryset().exclude(result=EventRecord.RESULT_REJECTED)
        params = self.request.query_params
        mapping = {
            'module': 'module',
            'category': 'category',
            'action': 'action',
            'result': 'result',
            'actor': 'actor_username',
            'resource_type': 'resource_type',
            'resource_id': 'resource_id',
            'environment': 'environment',
            'business_line': 'business_line',
            'application': 'application',
            'correlation_id': 'correlation_id',
        }
        for key, field in mapping.items():
            value = params.get(key, '').strip()
            if value:
                queryset = queryset.filter(**{field: value})
        if params.get('is_demo') in {'true', 'false'}:
            queryset = queryset.filter(is_demo=params.get('is_demo') == 'true')
        queryset, _, _ = _build_window(queryset, params, default_days=None)
        return queryset

    @action(detail=False, methods=['get'])
    def filter_options(self, request):
        queryset = self.get_queryset()
        return Response({
            'business_lines': list(queryset.exclude(business_line='').values_list('business_line', flat=True).distinct().order_by('business_line')[:50]),
            'environments': list(queryset.exclude(environment='').values_list('environment', flat=True).distinct().order_by('environment')[:50]),
            'applications': list(queryset.exclude(application='').values_list('application', flat=True).distinct().order_by('application')[:100]),
        })

    @action(detail=False, methods=['get'])
    def overview(self, request):
        recent, start, end = _build_window(self.get_queryset(), request.query_params, default_days=7)
        module_counts = list(recent.values('module').annotate(count=Count('id')).order_by('-count'))
        action_counts = list(recent.values('action').annotate(count=Count('id')).order_by('-count')[:8])
        applications = list(
            recent.exclude(application='')
            .values('application')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        business_lines = list(
            recent.exclude(business_line='')
            .values('business_line')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        environments = list(
            recent.exclude(environment='')
            .values('environment')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        scopes = [
            {
                'business_line': item['business_line'],
                'environment': item['environment'],
                'count': item['count'],
                'label': f"{item['business_line']} / {item['environment']}",
            }
            for item in (
                recent.exclude(business_line='')
                .exclude(environment='')
                .values('business_line', 'environment')
                .annotate(count=Count('id'))
                .order_by('-count')[:8]
            )
        ]
        actors = list(
            recent.exclude(actor_username='')
            .values('actor_username')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        recent_items = EventRecordSerializer(recent[:12], many=True).data
        priority_events = EventRecordSerializer(
            recent.filter(category='execution', result__in=[EventRecord.RESULT_FAILED, EventRecord.RESULT_PARTIAL])[:8],
            many=True,
        ).data
        return Response({
            'summary': {
                'total_7d': recent.count(),
                'failed_7d': recent.filter(result=EventRecord.RESULT_FAILED).count(),
                'pending_7d': recent.filter(result=EventRecord.RESULT_PENDING).count(),
                'unique_actors_7d': recent.exclude(actor_username='').values('actor_username').distinct().count(),
                'tracked_resources_7d': recent.exclude(resource_type='').values('resource_type', 'resource_id').distinct().count(),
            },
            'window': {
                'start_at': start,
                'end_at': end,
            },
            'modules': module_counts,
            'actions': action_counts,
            'top_actors': actors,
            'top_applications': applications,
            'top_business_lines': business_lines,
            'top_environments': environments,
            'top_scopes': scopes,
            'recent': recent_items,
            'high_risk': priority_events,
            'priority_events': priority_events,
            'failed_deployments': [],
            'rejected_sql': [],
            'execution_watchlist': priority_events,
            'tips': [
                '事件墙默认只保留最终执行结果和关键写操作，驳回但未执行的审批流不会进入事件墙。',
                '排查问题时优先按业务线、环境、应用缩小范围，再结合操作人和失败结果快速定位。',
            ],
        })

    @action(detail=False, methods=['get'])
    def associations(self, request):
        recent, _, _ = _build_window(self.get_queryset(), request.query_params, default_days=14)
        recent = recent[:400]
        chains = defaultdict(list)
        hot_resources = Counter()
        module_links = Counter()

        for item in recent:
            if item.correlation_id:
                chains[item.correlation_id].append(item)
            resource_key = f'{item.resource_type}:{item.resource_name or item.resource_id}'
            if item.resource_type:
                hot_resources[resource_key] += 1
            related_modules = {entry.get('module') for entry in (item.related_resources or []) if entry.get('module')}
            for related_module in related_modules:
                if related_module != item.module:
                    module_links[f'{item.module}->{related_module}'] += 1

        chain_payload = []
        for correlation_id, items in sorted(chains.items(), key=lambda pair: len(pair[1]), reverse=True)[:8]:
            ordered = sorted(items, key=lambda record: (record.occurred_at, record.id))
            chain_payload.append({
                'correlation_id': correlation_id,
                'count': len(ordered),
                'title': ordered[0].title,
                'modules': list(dict.fromkeys(item.module for item in ordered)),
                'latest_at': ordered[-1].occurred_at,
                'events': EventRecordSerializer(ordered[:6], many=True).data,
            })

        hot_resource_payload = [{'resource': key, 'count': count} for key, count in hot_resources.most_common(10)]
        module_link_payload = [{'link': key, 'count': count} for key, count in module_links.most_common(10)]
        return Response({
            'chains': chain_payload,
            'hot_resources': hot_resource_payload,
            'module_links': module_link_payload,
        })

