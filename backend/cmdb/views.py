from decimal import Decimal, InvalidOperation

from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Count, Sum, Avg, F, Q
from django.utils import timezone
from .models import CIType, ConfigItem, CIRelation, CostRecord, ResourceRequest, ResourceNode
from .serializers import (
    CITypeSerializer, ConfigItemSerializer, CIRelationSerializer,
    CostRecordSerializer, ResourceRequestSerializer, ResourceNodeSerializer
)
from rbac.permissions import RBACPermissionMixin, build_rbac_permission


def _current_month():
    return timezone.now().strftime('%Y-%m')


def _previous_months(limit=6):
    base = timezone.now().replace(day=1)
    months = []
    for _ in range(limit):
        months.append(base.strftime('%Y-%m'))
        base = (base - timezone.timedelta(days=1)).replace(day=1)
    months.reverse()
    return months


def _to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_float(value):
    return float(value or 0)


def _sync_cost_records_for_month(month):
    if month != _current_month():
        return

    for ci in ConfigItem.objects.all().only('id', 'attributes'):
        attributes = ci.attributes or {}
        amount = _to_decimal(attributes.get('monthly_cost'))
        if amount is None or amount <= 0:
            CostRecord.objects.filter(ci=ci, month=month).delete()
            continue
        CostRecord.objects.update_or_create(
            ci=ci,
            month=month,
            defaults={
                'amount': amount,
                'provider': (attributes.get('cloud_provider') or '')[:50],
            },
        )


def _cost_amount_for_ci(ci, month_costs):
    amount = month_costs.get(ci.id)
    if amount is not None:
        return amount
    return _to_decimal((ci.attributes or {}).get('monthly_cost')) or Decimal('0')


def _build_cost_report(month):
    _sync_cost_records_for_month(month)

    qs = CostRecord.objects.filter(month=month).select_related('ci__ci_type')
    by_business = [
        {
            'business_line': row['ci__business_line'] or 'Uncategorized',
            'total_cost': _to_float(row['total_cost']),
            'count': row['count'],
        }
        for row in qs.values('ci__business_line')
        .annotate(total_cost=Sum('amount'), count=Count('ci', distinct=True))
        .order_by('-total_cost', 'ci__business_line')
    ]
    by_environment = [
        {
            'environment': row['ci__environment'],
            'total_cost': _to_float(row['total_cost']),
            'count': row['count'],
        }
        for row in qs.values('ci__environment')
        .annotate(total_cost=Sum('amount'), count=Count('ci', distinct=True))
        .order_by('-total_cost', 'ci__environment')
    ]
    by_type = [
        {
            'type_name': row['ci__ci_type__name'],
            'total_cost': _to_float(row['total_cost']),
            'count': row['count'],
        }
        for row in qs.values('ci__ci_type__name')
        .annotate(total_cost=Sum('amount'), count=Count('ci', distinct=True))
        .order_by('-total_cost', 'ci__ci_type__name')
    ]
    by_provider = [
        {
            'provider': row['provider'] or 'Unknown',
            'total_cost': _to_float(row['total_cost']),
            'count': row['count'],
        }
        for row in qs.values('provider')
        .annotate(total_cost=Sum('amount'), count=Count('ci', distinct=True))
        .order_by('-total_cost', 'provider')
    ]

    top_cost_items = [
        {
            'ci_id': record.ci_id,
            'name': record.ci.name,
            'business_line': record.ci.business_line,
            'environment': record.ci.environment,
            'type_name': record.ci.ci_type.name,
            'monthly_cost': _to_float(record.amount),
            'provider': record.provider or '',
        }
        for record in qs.order_by('-amount', 'ci__name')[:10]
    ]

    trend_totals = {
        row['month']: _to_float(row['total'])
        for row in CostRecord.objects.values('month').annotate(total=Sum('amount'))
    }
    cost_trend = [
        {'period': period, 'total': trend_totals.get(period, 0)}
        for period in _previous_months()
    ]
    total = qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    return {
        'month': month,
        'total_monthly_cost': _to_float(total),
        'by_business': by_business,
        'by_environment': by_environment,
        'by_type': by_type,
        'by_provider': by_provider,
        'top_cost_items': top_cost_items,
        'cost_trend': cost_trend,
    }


def _build_optimization(month):
    _sync_cost_records_for_month(month)

    month_costs = {
        row['ci_id']: row['total_cost'] or Decimal('0')
        for row in CostRecord.objects.filter(month=month)
        .values('ci_id')
        .annotate(total_cost=Sum('amount'))
    }
    suggestions = []

    for ci in ConfigItem.objects.select_related('ci_type').all():
        monthly_cost = _cost_amount_for_ci(ci, month_costs)
        if monthly_cost <= 0:
            continue

        attributes = ci.attributes or {}
        cpu = _to_decimal(attributes.get('cpu')) or Decimal('0')
        memory_gb = _to_decimal(attributes.get('memory_gb')) or Decimal('0')
        suggestion = None

        if ci.status in {'offline', 'decommissioned'}:
            suggestion = {
                'type': 'reclaim',
                'severity': 'danger',
                'potential_saving': monthly_cost,
                'title': f'Reclaim unused resource: {ci.name}',
                'detail': 'Resource is offline. Recycle or delete it to stop paying for idle capacity.',
            }
        elif ci.status == 'idle':
            suggestion = {
                'type': 'reclaim',
                'severity': 'warning',
                'potential_saving': monthly_cost * Decimal('0.70'),
                'title': f'Review idle resource: {ci.name}',
                'detail': 'Resource is marked idle. Shut it down or convert it to lower-cost capacity.',
            }
        elif ci.environment in {'dev', 'test'} and monthly_cost >= Decimal('300'):
            suggestion = {
                'type': 'downsize',
                'severity': 'warning' if monthly_cost < Decimal('800') else 'danger',
                'potential_saving': monthly_cost * Decimal('0.30'),
                'title': f'Downsize non-production resource: {ci.name}',
                'detail': 'Non-production workloads usually do not need production-grade sizing all day.',
            }
        elif monthly_cost >= Decimal('1000') and (cpu >= Decimal('16') or memory_gb >= Decimal('32')):
            suggestion = {
                'type': 'downsize',
                'severity': 'warning',
                'potential_saving': monthly_cost * Decimal('0.20'),
                'title': f'Right-size high-cost resource: {ci.name}',
                'detail': 'Large instance specs and high monthly cost make this a good rightsizing candidate.',
            }
        elif not ci.business_line and monthly_cost >= Decimal('200'):
            suggestion = {
                'type': 'review',
                'severity': 'info',
                'potential_saving': monthly_cost * Decimal('0.10'),
                'title': f'Assign ownership for {ci.name}',
                'detail': 'Missing business ownership makes it harder to control spend and reclaim waste.',
            }

        if suggestion:
            suggestions.append({
                'ci_id': ci.id,
                'ci_name': ci.name,
                'environment': ci.environment,
                'business_line': ci.business_line,
                'monthly_cost': _to_float(monthly_cost),
                'potential_saving': _to_float(suggestion['potential_saving']),
                **suggestion,
            })

    suggestions.sort(key=lambda item: item['potential_saving'], reverse=True)
    return {
        'month': month,
        'suggestions': suggestions[:10],
        'total_potential_saving': round(sum(item['potential_saving'] for item in suggestions), 2),
        'suggestion_count': len(suggestions),
    }

class CITypeViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    """CI 类型管理"""
    queryset = CIType.objects.annotate(ci_count=Count('instances'))
    serializer_class = CITypeSerializer
    search_fields = ['name']
    pagination_class = None
    rbac_permissions = {
        'list': ['cmdb.ci.view'],
        'retrieve': ['cmdb.ci.view'],
        'create': ['cmdb.ci.manage'],
        'update': ['cmdb.ci.manage'],
        'partial_update': ['cmdb.ci.manage'],
        'destroy': ['cmdb.ci.manage'],
    }

class ConfigItemViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    """配置项管理"""
    queryset = ConfigItem.objects.select_related('ci_type').all()
    serializer_class = ConfigItemSerializer
    search_fields = ['name', 'admin_user', 'business_line']
    filterset_fields = ['ci_type', 'business_line', 'environment', 'status']
    rbac_permissions = {
        'list': ['cmdb.ci.view'],
        'retrieve': ['cmdb.ci.view'],
        'create': ['cmdb.ci.manage'],
        'update': ['cmdb.ci.manage'],
        'partial_update': ['cmdb.ci.manage'],
        'destroy': ['cmdb.ci.manage'],
        'stats': ['cmdb.ci.view'],
    }

    @action(detail=False, methods=['get'])
    def stats(self, request):
        qs = self.filter_queryset(self.get_queryset())
        by_type = list(qs.values('ci_type__name', 'ci_type__color').annotate(count=Count('id')).order_by('-count'))
        for item in by_type:
            item['ci_type__color'] = item.get('ci_type__color') or '#9c27b0'
        by_status = dict(qs.values_list('status').annotate(count=Count('id')))
        by_env = dict(qs.values_list('environment').annotate(count=Count('id')))
        return Response({
            'total': qs.count(),
            'by_type': by_type,
            'by_status': by_status,
            'by_env': by_env,
        })

class ResourceNodeViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    """资源节点(业务线/环境)树管理"""
    queryset = ResourceNode.objects.all().order_by('sort_order', 'id')
    serializer_class = ResourceNodeSerializer
    filterset_fields = ['node_type', 'parent']
    pagination_class = None
    rbac_permissions = {
        'list': ['cmdb.ci.view'],
        'retrieve': ['cmdb.ci.view'],
        'create': ['cmdb.ci.manage'],
        'update': ['cmdb.ci.manage'],
        'partial_update': ['cmdb.ci.manage'],
        'destroy': ['cmdb.ci.manage'],
        'tree': ['cmdb.ci.view'],
    }

    @action(detail=False, methods=['get'])
    def tree(self, request):
        nodes = list(ResourceNode.objects.all().order_by('sort_order', 'id').values())
        return Response(self._build_tree(nodes, None))

    def _build_tree(self, nodes, parent_id):
        tree = []
        for node in nodes:
            if node['parent_id'] == parent_id:
                children = self._build_tree(nodes, node['id'])
                if children:
                    node['children'] = children
                tree.append(node)
        return tree

class CIRelationViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    """CI 关系管理"""
    queryset = CIRelation.objects.select_related('source', 'target').all()
    serializer_class = CIRelationSerializer
    filterset_fields = ['source', 'target', 'relation_type']
    rbac_permissions = {
        'list': ['cmdb.ci.view'],
        'retrieve': ['cmdb.ci.view'],
        'create': ['cmdb.ci.manage'],
        'update': ['cmdb.ci.manage'],
        'partial_update': ['cmdb.ci.manage'],
        'destroy': ['cmdb.ci.manage'],
    }

class CostRecordViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    """成本记录管理"""
    queryset = CostRecord.objects.select_related('ci').all()
    serializer_class = CostRecordSerializer
    filterset_fields = ['ci', 'month']
    rbac_permissions = {
        'list': ['cmdb.cost.view'],
        'retrieve': ['cmdb.cost.view'],
        'create': ['cmdb.ci.manage'],
        'update': ['cmdb.ci.manage'],
        'partial_update': ['cmdb.ci.manage'],
        'destroy': ['cmdb.ci.manage'],
    }

class ResourceRequestViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    """资源申请管理"""
    queryset = ResourceRequest.objects.all()
    serializer_class = ResourceRequestSerializer
    search_fields = ['applicant', 'resource_type', 'reason']
    filterset_fields = ['status', 'resource_type']
    rbac_permissions = {
        'list': ['cmdb.ci.view'],
        'retrieve': ['cmdb.ci.view'],
        'create': ['cmdb.request.submit'],
        'update': ['cmdb.request.approve'],
        'partial_update': ['cmdb.request.approve'],
        'destroy': ['cmdb.request.approve'],
        'approve': ['cmdb.request.approve'],
        'reject': ['cmdb.request.approve'],
        'complete': ['cmdb.request.approve'],
    }

    def perform_create(self, serializer):
        serializer.save(applicant=self.request.user.username)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        obj = self.get_object()
        if obj.status != 'pending':
            return Response({'detail': '只能审批待审批资源'}, status=400)
        obj.status = 'approved'
        obj.save(update_fields=['status'])
        return Response(ResourceRequestSerializer(obj).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        obj = self.get_object()
        if obj.status != 'pending':
            return Response({'detail': '只能审批待审批资源'}, status=400)
        obj.status = 'rejected'
        obj.save(update_fields=['status'])
        return Response(ResourceRequestSerializer(obj).data)
    
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        obj = self.get_object()
        if obj.status != 'approved':
            return Response({'detail': '只能完成已批准资源'}, status=400)
        obj.status = 'provisioned'
        obj.save(update_fields=['status'])
        return Response(ResourceRequestSerializer(obj).data)

@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('cmdb.dashboard.view')])
def cmdb_dashboard(request):
    month = _current_month()
    _sync_cost_records_for_month(month)
    ci_total = ConfigItem.objects.count()
    ci_active = ConfigItem.objects.filter(status='active').count()
    ci_by_type = list(ConfigItem.objects.values(type_name=F('ci_type__name'), color=F('ci_type__color')).annotate(count=Count('id')).order_by('-count'))
    for item in ci_by_type:
        item['color'] = item.get('color') or '#9c27b0'
    ci_by_env = list(ConfigItem.objects.values('environment').annotate(count=Count('id')).order_by('-count'))
    ci_by_biz = list(
        ConfigItem.objects.exclude(business_line='')
        .values('business_line')
        .annotate(
            count=Count('id'),
            total_cost=Sum('costs__amount', filter=Q(costs__month=month)),
        )
        .order_by('-total_cost')
    )
    for item in ci_by_biz:
        item['total_cost'] = _to_float(item['total_cost'])
    total_monthly_cost = CostRecord.objects.filter(month=month).aggregate(total=Sum('amount'))['total'] or 0
    relation_count = CIRelation.objects.count()
    pending_requests = ResourceRequest.objects.filter(status='pending').count()

    return Response({
        'ci_total': ci_total,
        'ci_active': ci_active,
        'ci_by_type': ci_by_type,
        'ci_by_env': ci_by_env,
        'ci_by_business': ci_by_biz,
        'total_monthly_cost': _to_float(total_monthly_cost),
        'relation_count': relation_count,
        'pending_requests': pending_requests,
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('cmdb.topology.view')])
def cmdb_topology(request):
    ci_type_id = request.query_params.get('ci_type')
    business_line = request.query_params.get('business_line')
    environment = request.query_params.get('environment')
    scope = request.query_params.get('scope', 'neighbors')
    include_neighbors = scope != 'exact'

    filtered_qs = ConfigItem.objects.select_related('ci_type').all()
    if ci_type_id:
        filtered_qs = filtered_qs.filter(ci_type_id=ci_type_id)
    if business_line:
        filtered_qs = filtered_qs.filter(business_line=business_line)
    if environment:
        filtered_qs = filtered_qs.filter(environment=environment)

    matched_ids = set(filtered_qs.values_list('id', flat=True))
    node_ids = set(matched_ids)
    relations = CIRelation.objects.none()
    if matched_ids:
        relations = CIRelation.objects.filter(
            Q(source_id__in=matched_ids) | Q(target_id__in=matched_ids)
        ).select_related('source', 'target')
        if include_neighbors:
            for relation in relations:
                node_ids.add(relation.source_id)
                node_ids.add(relation.target_id)

    node_qs = ConfigItem.objects.select_related('ci_type').filter(id__in=node_ids).order_by(
        'business_line',
        'environment',
        'ci_type__name',
        'name',
    )
    nodes = []
    for ci in node_qs:
        attributes = ci.attributes or {}
        nodes.append({
            'id': ci.id,
            'name': ci.name,
            'type': ci.ci_type.name,
            'icon': ci.ci_type.icon,
            'color': ci.ci_type.color or '#9c27b0',
            'status': ci.status,
            'ip': attributes.get('ip_address') or attributes.get('ip', ''),
            'env': ci.environment,
            'business_line': ci.business_line,
            'admin_user': ci.admin_user,
            'monthly_cost': _to_float(attributes.get('monthly_cost')),
            'instance_type': attributes.get('instance_type', ''),
            'cloud_provider': attributes.get('cloud_provider', ''),
            'region': attributes.get('region', ''),
            'cpu': attributes.get('cpu'),
            'memory_gb': attributes.get('memory_gb'),
            'disk_gb': attributes.get('disk_gb'),
            'description': attributes.get('description', ''),
            'is_match': ci.id in matched_ids,
        })

    filtered_edges = []
    if node_ids:
        if not matched_ids:
            relations = CIRelation.objects.none()
        elif not include_neighbors:
            relations = CIRelation.objects.filter(
                source_id__in=node_ids,
                target_id__in=node_ids,
            ).select_related('source', 'target')
        for relation in relations:
            if relation.source_id in node_ids and relation.target_id in node_ids:
                filtered_edges.append({
                    'id': relation.id,
                    'source': relation.source_id,
                    'target': relation.target_id,
                    'source_name': relation.source.name,
                    'target_name': relation.target.name,
                    'type': relation.relation_type,
                    'label': relation.get_relation_type_display(),
                    'description': relation.description,
                    'is_match': relation.source_id in matched_ids and relation.target_id in matched_ids,
                })

    return Response({
        'nodes': nodes,
        'edges': filtered_edges,
        'meta': {
            'scope': 'neighbors' if include_neighbors else 'exact',
            'matched_node_ids': sorted(matched_ids),
            'node_count': len(nodes),
            'edge_count': len(filtered_edges),
        },
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('cmdb.cost.view')])
def cmdb_cost_report(request):
    month = request.query_params.get('month') or _current_month()
    return Response(_build_cost_report(month))

@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('cmdb.cost.view')])
def cmdb_optimization(request):
    month = request.query_params.get('month') or _current_month()
    return Response(_build_optimization(month))
