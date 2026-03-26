import paramiko
from django.db.models import Avg, Count
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rbac.permissions import RBACPermissionMixin, build_rbac_permission

from . import deployer
from .models import Alert, Deployment, DeploymentApprovalFlow, DeploymentApprovalStep, Host, LogEntry
from .serializers import (
    AlertSerializer,
    ApprovalActionSerializer,
    DeploymentActionSerializer,
    DeploymentApprovalFlowSerializer,
    DeploymentSerializer,
    HostSerializer,
    LogEntrySerializer,
)


def _resolve_approval_flow(environment):
    flow = DeploymentApprovalFlow.objects.filter(is_active=True, environment=environment).prefetch_related('nodes').first()
    if flow:
        return flow
    return DeploymentApprovalFlow.objects.filter(is_active=True, environment='').prefetch_related('nodes').first()


def _initialize_approval_steps(deployment):
    flow = _resolve_approval_flow(deployment.environment)
    deployment.approval_flow = flow
    deployment.save(update_fields=['approval_flow'])
    deployment.approval_steps.all().delete()
    if not flow:
        return
    steps = []
    nodes = list(flow.nodes.all().order_by('order', 'id'))
    for index, node in enumerate(nodes):
        steps.append(
            DeploymentApprovalStep(
                deployment=deployment,
                flow=flow,
                node_name=node.name,
                node_order=node.order,
                approver_type=node.approver_type,
                approver_value=node.approver_value,
                is_current=index == 0,
            )
        )
    DeploymentApprovalStep.objects.bulk_create(steps)


def _match_step_approver(user, step):
    if user.is_superuser:
        return True
    if not step or not step.approver_value:
        return True
    if step.approver_type == 'user':
        return user.username == step.approver_value
    if step.approver_type == 'role':
        return user.rbac_roles.filter(code=step.approver_value).exists()
    if step.approver_type == 'group':
        return user.rbac_groups.filter(code=step.approver_value).exists()
    return True


class HostViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = Host.objects.all()
    serializer_class = HostSerializer
    search_fields = ['hostname', 'ip_address']
    rbac_permissions = {
        'list': ['ops.host.view'],
        'retrieve': ['ops.host.view'],
        'create': ['ops.host.manage'],
        'update': ['ops.host.manage'],
        'partial_update': ['ops.host.manage'],
        'destroy': ['ops.host.manage'],
        'test_connection': ['ops.host.manage'],
        'refresh_info': ['ops.host.manage'],
    }

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        host = self.get_object()
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host.ip_address,
                port=host.ssh_port or 22,
                username=host.ssh_user or 'root',
                password=host.ssh_password or None,
                timeout=10,
            )
            stdin, stdout, stderr = client.exec_command('uname -a', timeout=5)
            uname = stdout.read().decode('utf-8', errors='replace').strip()
            client.close()
            return Response({'success': True, 'message': f'连接成功: {uname}'})
        except Exception as exc:
            return Response({'success': False, 'message': f'连接失败: {str(exc)}'})

    @action(detail=True, methods=['post'])
    def refresh_info(self, request, pk=None):
        host = self.get_object()
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=host.ip_address,
                port=host.ssh_port or 22,
                username=host.ssh_user or 'root',
                password=host.ssh_password or None,
                timeout=10,
            )

            def run_cmd(command):
                stdin, stdout, stderr = client.exec_command(command, timeout=5)
                return stdout.read().decode('utf-8', errors='replace').strip()

            try:
                host.cpu_usage = round(float(run_cmd("top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")), 1)
            except (ValueError, TypeError):
                pass
            try:
                host.memory_usage = round(float(run_cmd("free | grep Mem | awk '{printf(\"%.1f\", $3/$2*100)}'")), 1)
            except (ValueError, TypeError):
                pass
            try:
                host.disk_usage = round(float(run_cmd("df / | tail -1 | awk '{print $5}' | tr -d '%'")), 1)
            except (ValueError, TypeError):
                pass

            host.status = 'online'
            host.save(update_fields=['cpu_usage', 'memory_usage', 'disk_usage', 'status'])
            client.close()
            return Response(HostSerializer(host).data)
        except Exception as exc:
            host.status = 'offline'
            host.save(update_fields=['status'])
            return Response({'detail': f'获取信息失败: {str(exc)}'}, status=400)


class DeploymentApprovalFlowViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = DeploymentApprovalFlow.objects.prefetch_related('nodes').all()
    serializer_class = DeploymentApprovalFlowSerializer
    search_fields = ['name', 'description']
    rbac_permissions = {
        'list': ['ops.deployment.view'],
        'retrieve': ['ops.deployment.view'],
        'create': ['ops.deployment.manage'],
        'update': ['ops.deployment.manage'],
        'partial_update': ['ops.deployment.manage'],
        'destroy': ['ops.deployment.manage'],
    }

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.username)


class DeploymentViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = Deployment.objects.select_related(
        'host',
        'docker_host',
        'cluster',
        'approval_flow',
        'previous_success',
        'rollback_source',
        'rerun_source',
    ).prefetch_related('approval_steps').all()
    serializer_class = DeploymentSerializer
    search_fields = ['app_name', 'business_line', 'version', 'image', 'submitter', 'deployer']
    filterset_fields = ['business_line', 'environment', 'deploy_mode', 'approval_status', 'status', 'release_strategy']
    rbac_permissions = {
        'list': ['ops.deployment.view'],
        'retrieve': ['ops.deployment.view'],
        'create': ['ops.deployment.manage'],
        'update': ['ops.deployment.manage'],
        'partial_update': ['ops.deployment.manage'],
        'destroy': ['ops.deployment.manage'],
        'approve': ['ops.deployment.approve'],
        'reject': ['ops.deployment.approve'],
        'stop': ['ops.deployment.manage'],
        'start': ['ops.deployment.manage'],
        'remove': ['ops.deployment.manage'],
        'logs': ['ops.deployment.view'],
        'status_detail': ['ops.deployment.view'],
        'rerun': ['ops.deployment.manage'],
        'rollback': ['ops.deployment.manage'],
        'advance_batch': ['ops.deployment.manage'],
    }

    def perform_create(self, serializer):
        deployment = serializer.save(submitter=self.request.user.username)
        _initialize_approval_steps(deployment)

    def _clone_release(
        self,
        source,
        actor,
        action_type,
        change_summary='',
        previous_success=None,
        rollback_source=None,
        rerun_source=None,
    ):
        deployment = Deployment.objects.create(
            app_name=source.app_name,
            business_line=source.business_line,
            version=source.version,
            image=source.image,
            environment=source.environment,
            deploy_mode=source.deploy_mode,
            release_strategy=source.release_strategy,
            submitter=actor,
            host=source.host,
            docker_host=source.docker_host,
            cluster=source.cluster,
            namespace=source.namespace,
            release_name=source.release_name,
            replicas=source.replicas,
            container_port=source.container_port,
            service_port=source.service_port,
            canary_percent=source.canary_percent,
            batch_total=source.batch_total,
            batch_size=source.batch_size,
            strategy_config=dict(source.strategy_config or {}),
            env_config=dict(source.env_config or {}),
            description=source.description,
            change_summary=change_summary,
            action_type=action_type,
            previous_success=previous_success,
            rollback_source=rollback_source,
            rerun_source=rerun_source,
        )
        _initialize_approval_steps(deployment)
        return deployment

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        deployment = self.get_object()
        if deployment.approval_status != 'pending':
            return Response({'detail': '只能审批待审批的发布单'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ApprovalActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.validated_data.get('comment', '')
        current_step = deployment.current_approval_step
        if current_step and not _match_step_approver(request.user, current_step):
            return Response({'detail': '当前账号不在该审批节点的审批范围内'}, status=status.HTTP_403_FORBIDDEN)

        if current_step:
            current_step.status = 'approved'
            current_step.is_current = False
            current_step.approver = request.user.username
            current_step.comment = comment
            current_step.acted_at = timezone.now()
            current_step.save(update_fields=['status', 'is_current', 'approver', 'comment', 'acted_at'])

            next_step = deployment.approval_steps.filter(status='pending').order_by('node_order', 'id').first()
            deployment.approver = request.user.username
            deployment.approval_comment = comment
            if next_step:
                next_step.is_current = True
                next_step.save(update_fields=['is_current'])
                deployment.save(update_fields=['approver', 'approval_comment'])
                return Response(DeploymentSerializer(deployment).data)

        deployment.approval_status = 'approved'
        deployment.approver = request.user.username
        deployment.approval_comment = comment
        deployment.approved_at = timezone.now()
        deployment.deployer = request.user.username
        deployment.save(update_fields=['approval_status', 'approver', 'approval_comment', 'approved_at', 'deployer'])
        deployer.start_deployment_thread(deployment.id)
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        deployment = self.get_object()
        if deployment.approval_status != 'pending':
            return Response({'detail': '只能驳回待审批的发布单'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ApprovalActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.validated_data.get('comment', '')
        current_step = deployment.current_approval_step
        if current_step and not _match_step_approver(request.user, current_step):
            return Response({'detail': '当前账号不在该审批节点的审批范围内'}, status=status.HTTP_403_FORBIDDEN)

        if current_step:
            current_step.status = 'rejected'
            current_step.is_current = False
            current_step.approver = request.user.username
            current_step.comment = comment
            current_step.acted_at = timezone.now()
            current_step.save(update_fields=['status', 'is_current', 'approver', 'comment', 'acted_at'])
            deployment.approval_steps.filter(status='pending').update(is_current=False)

        deployment.approval_status = 'rejected'
        deployment.status = 'rejected'
        deployment.approver = request.user.username
        deployment.approval_comment = comment
        deployment.approved_at = timezone.now()
        deployment.save(update_fields=['approval_status', 'status', 'approver', 'approval_comment', 'approved_at'])
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def rerun(self, request, pk=None):
        deployment = self.get_object()
        serializer = DeploymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_release = self._clone_release(
            deployment,
            actor=request.user.username,
            action_type='rerun',
            change_summary=serializer.validated_data.get('change_summary') or f'重新执行 #{deployment.id}',
            previous_success=deployment if deployment.approval_status == 'approved' and deployment.execution_count else deployment.previous_success,
            rerun_source=deployment,
        )
        return Response(DeploymentSerializer(new_release).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def rollback(self, request, pk=None):
        deployment = self.get_object()
        previous_release = deployment.get_previous_successful_release()
        if not previous_release:
            return Response({'detail': '未找到可回滚的历史成功版本'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = DeploymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_release = self._clone_release(
            previous_release,
            actor=request.user.username,
            action_type='rollback',
            change_summary=serializer.validated_data.get('change_summary') or f'回滚到 v{previous_release.version}',
            previous_success=deployment if deployment.approval_status == 'approved' and deployment.execution_count else deployment.previous_success,
            rollback_source=deployment,
        )
        return Response(DeploymentSerializer(new_release).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def advance_batch(self, request, pk=None):
        deployment = self.get_object()
        serializer = DeploymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            deployer.advance_batch(
                deployment,
                actor=request.user.username,
                change_summary=serializer.validated_data.get('change_summary', ''),
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        deployment = self.get_object()
        deployer.stop_service(deployment)
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        deployment = self.get_object()
        deployer.start_service(deployment)
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['post'])
    def remove(self, request, pk=None):
        deployment = self.get_object()
        deployer.remove_service(deployment)
        return Response(DeploymentSerializer(deployment).data)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        deployment = self.get_object()
        tail = int(request.query_params.get('tail', 100))
        return Response({'logs': deployer.get_service_logs(deployment, tail=tail)})

    @action(detail=True, methods=['get'])
    def status_detail(self, request, pk=None):
        deployment = self.get_object()
        return Response(deployer.get_service_status(deployment))


class AlertViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = Alert.objects.select_related('host').all()
    serializer_class = AlertSerializer
    search_fields = ['title', 'source', 'message']
    rbac_permissions = {
        'list': ['ops.alert.view'],
        'retrieve': ['ops.alert.view'],
        'create': ['ops.alert.manage'],
        'update': ['ops.alert.manage'],
        'partial_update': ['ops.alert.manage'],
        'destroy': ['ops.alert.manage'],
    }


class LogEntryViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = LogEntry.objects.select_related('host').all()
    serializer_class = LogEntrySerializer
    search_fields = ['service', 'message']
    rbac_permissions = {
        'list': ['ops.log.entry.view'],
        'retrieve': ['ops.log.entry.view'],
        'create': ['ops.log.entry.manage'],
        'update': ['ops.log.entry.manage'],
        'partial_update': ['ops.log.entry.manage'],
        'destroy': ['ops.log.entry.manage'],
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.dashboard.view')])
def dashboard_stats(request):
    host_total = Host.objects.count()
    host_status = dict(Host.objects.values_list('status').annotate(count=Count('id')).values_list('status', 'count'))
    host_avg = Host.objects.aggregate(
        avg_cpu=Avg('cpu_usage'),
        avg_memory=Avg('memory_usage'),
        avg_disk=Avg('disk_usage'),
    )

    deploy_total = Deployment.objects.count()
    deploy_running = Deployment.objects.filter(status='running', is_current=True).count()
    deploy_failed = Deployment.objects.filter(status__in=['failed', 'rejected']).count()
    deploy_success = Deployment.objects.filter(status__in=['running', 'stopped', 'removed']).count()

    alert_total = Alert.objects.count()
    alert_unacked = Alert.objects.filter(is_acknowledged=False).count()
    alert_levels = dict(Alert.objects.values_list('level').annotate(count=Count('id')).values_list('level', 'count'))

    recent_deploys = DeploymentSerializer(
        Deployment.objects.select_related('host', 'docker_host', 'cluster', 'approval_flow').prefetch_related('approval_steps').all()[:10],
        many=True,
    ).data
    recent_alerts = AlertSerializer(
        Alert.objects.select_related('host').filter(is_acknowledged=False)[:10],
        many=True,
    ).data

    return Response({
        'hosts': {
            'total': host_total,
            'online': host_status.get('online', 0),
            'offline': host_status.get('offline', 0),
            'warning': host_status.get('warning', 0),
            'avg_cpu': round(host_avg['avg_cpu'] or 0, 1),
            'avg_memory': round(host_avg['avg_memory'] or 0, 1),
            'avg_disk': round(host_avg['avg_disk'] or 0, 1),
        },
        'deployments': {
            'total': deploy_total,
            'success': deploy_success,
            'failed': deploy_failed,
            'running': deploy_running,
        },
        'alerts': {
            'total': alert_total,
            'unacknowledged': alert_unacked,
            'critical': alert_levels.get('critical', 0),
            'warning': alert_levels.get('warning', 0),
            'info': alert_levels.get('info', 0),
        },
        'recent_deploys': recent_deploys,
        'recent_alerts': recent_alerts,
    })
