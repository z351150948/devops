import json
import random
from datetime import timedelta

from django.db import connection
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from cmdb.demo_seed import BIZ_COMMERCE, BIZ_DATA, BIZ_INFRA, seed_cmdb_demo
from marketplace.models import ServiceDeployment, ServiceTemplate
from ops.deployer import sync_current_deployments_to_cmdb
from ops.models import (
    Alert,
    Deployment,
    DeploymentApprovalFlow,
    DeploymentApprovalNode,
    DeploymentApprovalStep,
    DockerHost,
    Host,
    K8sCluster,
    LogEntry,
)


def seed_marketplace_demo(stdout, hosts):
    stdout.write('正在生成工具市场演示数据...')
    call_command('seed_templates')
    ServiceDeployment.objects.all().delete()

    cluster_main, _ = K8sCluster.objects.update_or_create(
        name='demo-k8s-cluster',
        defaults={
            'api_server': 'https://demo-k8s-cluster.example.local:6443',
            'kubeconfig': 'demo',
            'status': 'connected',
            'description': '工具市场演示 Kubernetes 集群',
        },
    )
    cluster_dev, _ = K8sCluster.objects.update_or_create(
        name='dev-k8s-cluster',
        defaults={
            'api_server': 'https://dev-k8s-cluster.example.local:6443',
            'kubeconfig': 'demo',
            'status': 'connected',
            'description': '开发环境演示 Kubernetes 集群',
        },
    )

    template_map = {
        item.name: item
        for item in ServiceTemplate.objects.filter(
            name__in=['Redis', 'MongoDB', 'Nginx', 'Grafana', 'Java', 'Python', 'Node.js']
        )
    }
    host_map = {host.hostname: host for host in hosts}

    deployments = [
        {
            'template': template_map['Redis'],
            'deploy_mode': 'docker_compose',
            'host': host_map['feature-x-dev-ecs'],
            'version': '7.0',
            'status': 'running',
            'env_config': {'port': '6379', 'password': 'redis@2024'},
            'deployer': 'ops-demo',
            'deploy_dir': '/opt/agdevops/redis',
            'deploy_log': '[INFO] Docker Compose 部署成功',
        },
        {
            'template': template_map['MongoDB'],
            'deploy_mode': 'docker_compose',
            'host': host_map['legacy-data-sync'],
            'version': '7.0',
            'status': 'stopped',
            'env_config': {'port': '27017', 'root_username': 'admin', 'root_password': 'mongo@2024'},
            'deployer': 'admin',
            'deploy_dir': '/opt/agdevops/mongodb',
            'deploy_log': '[INFO] MongoDB 已部署，当前处于停止状态',
        },
        {
            'template': template_map['Nginx'],
            'deploy_mode': 'docker_compose',
            'host': host_map['order-api-ecs-01'],
            'version': '1.25',
            'status': 'failed',
            'env_config': {'http_port': '80', 'https_port': '443'},
            'deployer': 'zhangsan',
            'deploy_dir': '/opt/agdevops/nginx',
            'deploy_log': '[ERROR] 端口 80 被占用，部署失败',
        },
        {
            'template': template_map['Grafana'],
            'deploy_mode': 'k8s',
            'cluster': cluster_main,
            'namespace': 'monitoring',
            'release_name': 'grafana-demo',
            'replicas': 1,
            'version': '10.3',
            'status': 'running',
            'env_config': {'port': '3000'},
            'deployer': 'ops-demo',
            'deploy_dir': 'k8s://demo-k8s-cluster/monitoring/grafana-demo',
            'deploy_log': '[INFO] Grafana K8s 部署成功',
        },
        {
            'template': template_map['Java'],
            'deploy_mode': 'k8s',
            'cluster': cluster_dev,
            'namespace': 'devenv',
            'release_name': 'java-devbox',
            'replicas': 1,
            'version': '3.9.9-eclipse-temurin-21',
            'status': 'running',
            'env_config': {'workspace': '/workspace'},
            'deployer': 'dev-demo',
            'deploy_dir': 'k8s://dev-k8s-cluster/devenv/java-devbox',
            'deploy_log': '[INFO] Java 开发环境已创建',
        },
        {
            'template': template_map['Python'],
            'deploy_mode': 'k8s',
            'cluster': cluster_dev,
            'namespace': 'devenv',
            'release_name': 'python-devbox',
            'replicas': 1,
            'version': '3.12',
            'status': 'running',
            'env_config': {'workspace': '/workspace'},
            'deployer': 'dev-demo',
            'deploy_dir': 'k8s://dev-k8s-cluster/devenv/python-devbox',
            'deploy_log': '[INFO] Python 开发环境已创建',
        },
        {
            'template': template_map['Node.js'],
            'deploy_mode': 'k8s',
            'cluster': cluster_dev,
            'namespace': 'frontend-dev',
            'release_name': 'nodejs-devbox',
            'replicas': 1,
            'version': '20',
            'status': 'deploying',
            'env_config': {'workspace': '/workspace'},
            'deployer': 'dev-demo',
            'deploy_dir': 'k8s://dev-k8s-cluster/frontend-dev/nodejs-devbox',
            'deploy_log': '[INFO] 正在拉取 node:20 镜像',
        },
    ]

    for item in deployments:
        create_marketplace_deployment(item)


def create_marketplace_deployment(item):
    columns = set()
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA table_info(marketplace_servicedeployment)')
        columns = {row[1] for row in cursor.fetchall()}

    now = timezone.now()
    status_value = item.get('status', 'pending')
    payload = {
        'template_id': item['template'].id,
        'deploy_mode': item.get('deploy_mode', 'docker_compose'),
        'host_id': item['host'].id if item.get('host') else None,
        'cluster_id': item['cluster'].id if item.get('cluster') else None,
        'namespace': item.get('namespace', ''),
        'release_name': item.get('release_name', ''),
        'replicas': item.get('replicas', 1),
        'version': item['version'],
        'status': status_value,
        'env_config': json.dumps(item.get('env_config', {}), ensure_ascii=False),
        'deploy_log': item.get('deploy_log', ''),
        'deployer': item.get('deployer', 'admin'),
        'deploy_dir': item.get('deploy_dir', ''),
        'created_at': now,
        'updated_at': now,
        'action_type': 'deploy',
        'approval_comment': '',
        'approval_status': 'approved',
        'approved_at': now,
        'approver': item.get('deployer', 'admin'),
        'change_summary': '工具市场演示数据',
        'executed_at': now,
        'execution_count': 1,
        'finished_at': now,
        'is_current': status_value in {'running', 'stopped'},
        'submitter': item.get('deployer', 'admin'),
        'previous_success_id': None,
        'rerun_source_id': None,
        'rollback_source_id': None,
    }

    insert_columns = [name for name in payload.keys() if name in columns]
    placeholders = ', '.join(['%s'] * len(insert_columns))
    sql = f'INSERT INTO marketplace_servicedeployment ({", ".join(insert_columns)}) VALUES ({placeholders})'
    values = [payload[name] for name in insert_columns]
    with connection.cursor() as cursor:
        cursor.execute(sql, values)


def _create_approval_steps(deployment, statuses):
    nodes = list(deployment.approval_flow.nodes.all().order_by('order'))
    steps = []
    for index, node in enumerate(nodes):
        status_value = statuses[index]
        previous_pending = any(item == 'pending' for item in statuses[:index])
        steps.append(
            DeploymentApprovalStep(
                deployment=deployment,
                flow=deployment.approval_flow,
                node_name=node.name,
                node_order=node.order,
                approver_type=node.approver_type,
                approver_value=node.approver_value,
                status=status_value,
                is_current=status_value == 'pending' and not previous_pending,
                approver='ops-admin' if status_value == 'approved' else '',
                comment='演示审批通过' if status_value == 'approved' else '',
                acted_at=deployment.approved_at if status_value == 'approved' else None,
            )
        )
    DeploymentApprovalStep.objects.bulk_create(steps)


def seed_app_release_demo(stdout, hosts, docker_hosts):
    stdout.write('正在生成应用发布演示数据...')

    cluster_prod, _ = K8sCluster.objects.update_or_create(
        name='app-prod-k8s',
        defaults={
            'api_server': 'https://app-prod-k8s.example.local:6443',
            'kubeconfig': 'demo',
            'status': 'connected',
            'description': '应用发布生产集群演示环境',
        },
    )
    cluster_gray, _ = K8sCluster.objects.update_or_create(
        name='app-gray-k8s',
        defaults={
            'api_server': 'https://app-gray-k8s.example.local:6443',
            'kubeconfig': 'demo',
            'status': 'connected',
            'description': '应用发布灰度集群演示环境',
        },
    )

    flow_prod = DeploymentApprovalFlow.objects.create(
        name='生产发布三段审批',
        environment='prod',
        description='研发负责人、产品负责人、运维负责人三级审批',
        is_active=True,
        created_by='ops-demo',
    )
    DeploymentApprovalNode.objects.bulk_create([
        DeploymentApprovalNode(flow=flow_prod, name='研发负责人审批', order=1, approver_type='user', approver_value='ops-admin'),
        DeploymentApprovalNode(flow=flow_prod, name='产品负责人审批', order=2, approver_type='role', approver_value='platform-admin'),
        DeploymentApprovalNode(flow=flow_prod, name='运维负责人审批', order=3, approver_type='group', approver_value='ops-team'),
    ])

    flow_staging = DeploymentApprovalFlow.objects.create(
        name='测试快速审批',
        environment='test',
        description='测试环境双节点审批',
        is_active=True,
        created_by='ops-demo',
    )
    DeploymentApprovalNode.objects.bulk_create([
        DeploymentApprovalNode(flow=flow_staging, name='研发自检', order=1, approver_type='user', approver_value='zhangsan'),
        DeploymentApprovalNode(flow=flow_staging, name='运维确认', order=2, approver_type='user', approver_value='ops-admin'),
    ])

    docker_host_map = {host.name: host for host in docker_hosts}
    app_docker_env = docker_host_map.get('app-release-test') or docker_hosts[0]
    gateway_docker_env = docker_host_map.get('gateway-prod') or docker_hosts[1]

    release_items = [
        {
            'app_name': 'erp-platform',
            'business_line': BIZ_COMMERCE,
            'version': 'v5.2.0',
            'image': 'registry.demo.local/erp-platform:v5.2.0',
            'environment': 'prod',
            'deploy_mode': 'k8s',
            'release_strategy': 'standard',
            'status': 'running',
            'approval_status': 'approved',
            'submitter': 'zhangsan',
            'deployer': 'ops-admin',
            'approver': 'ops-admin',
            'approval_comment': '生产窗口已确认',
            'change_summary': 'ERP 平台生产正式发布',
            'description': '典型案例：生产 K8s 标准发布',
            'cluster': cluster_prod,
            'namespace': 'erp-prod',
            'release_name': 'erp-platform-prod',
            'replicas': 3,
            'container_port': 8080,
            'service_port': 80,
            'approval_flow': flow_prod,
            'execution_count': 1,
            'is_current': True,
            'approved_at': timezone.now() - timedelta(days=2, minutes=10),
            'executed_at': timezone.now() - timedelta(days=2, minutes=5),
            'finished_at': timezone.now() - timedelta(days=2),
            'deploy_dir': 'k8s://app-prod-k8s/erp-prod/erp-platform-prod',
            'deploy_log': '[INFO] 发布模式: K8s 集群\n[INFO] 发布策略: 标准发布\n[SUCCESS] Deployment/erp-platform-prod 已发布',
            'deployed_at': timezone.now() - timedelta(days=2),
            'step_statuses': ['approved', 'approved', 'approved'],
        },
        {
            'app_name': 'gateway-service',
            'business_line': BIZ_COMMERCE,
            'version': 'v3.8.1',
            'image': 'registry.demo.local/gateway-service:v3.8.1',
            'environment': 'prod',
            'deploy_mode': 'k8s',
            'release_strategy': 'canary',
            'canary_percent': 20,
            'status': 'running',
            'approval_status': 'approved',
            'submitter': 'lisi',
            'deployer': 'ops-admin',
            'approver': 'ops-admin',
            'approval_comment': '灰度计划已确认',
            'change_summary': '网关服务 20% 灰度发布',
            'description': '典型案例：生产 K8s 灰度发布',
            'cluster': cluster_gray,
            'namespace': 'gateway-prod',
            'release_name': 'gateway-service-canary',
            'replicas': 2,
            'container_port': 8080,
            'service_port': 80,
            'approval_flow': flow_prod,
            'execution_count': 1,
            'is_current': True,
            'approved_at': timezone.now() - timedelta(days=1, hours=2, minutes=8),
            'executed_at': timezone.now() - timedelta(days=1, hours=2, minutes=5),
            'finished_at': timezone.now() - timedelta(days=1, hours=2),
            'deploy_dir': 'k8s://app-gray-k8s/gateway-prod/gateway-service-canary',
            'deploy_log': '[INFO] 发布模式: K8s 集群\n[INFO] 发布策略: 灰度发布 20%\n[SUCCESS] Canary Deployment/gateway-service-canary 已发布',
            'deployed_at': timezone.now() - timedelta(days=1, hours=2),
            'step_statuses': ['approved', 'approved', 'approved'],
        },
        {
            'app_name': 'order-center',
            'business_line': BIZ_COMMERCE,
            'version': 'v2.6.0',
            'image': 'registry.demo.local/order-center:v2.6.0',
            'environment': 'test',
            'deploy_mode': 'docker_compose',
            'release_strategy': 'batch',
            'batch_total': 3,
            'batch_current': 2,
            'batch_size': 2,
            'status': 'running',
            'approval_status': 'approved',
            'submitter': 'wangwu',
            'deployer': 'ops-admin',
            'approver': 'ops-admin',
            'approval_comment': '第二批次验证正常',
            'change_summary': '订单中心分三批发布，当前第二批',
            'description': '典型案例：测试环境 Docker 批次发布',
            'docker_host': app_docker_env,
            'container_port': 8081,
            'service_port': 8081,
            'approval_flow': flow_staging,
            'execution_count': 1,
            'is_current': True,
            'approved_at': timezone.now() - timedelta(hours=8, minutes=6),
            'executed_at': timezone.now() - timedelta(hours=8, minutes=3),
            'finished_at': timezone.now() - timedelta(hours=8),
            'deploy_dir': '/opt/agdevops/apps/order-center-test',
            'deploy_log': '[INFO] 发布模式: Docker 环境\n[INFO] 发布策略: 批次发布，共 3 批，单批规模 2\n[INFO] 批次推进: 第 2/3 批',
            'deployed_at': timezone.now() - timedelta(hours=8),
            'step_statuses': ['approved', 'approved'],
        },
        {
            'app_name': 'admin-portal',
            'business_line': BIZ_DATA,
            'version': 'v1.9.3',
            'image': 'registry.demo.local/admin-portal:v1.9.3',
            'environment': 'prod',
            'deploy_mode': 'docker_compose',
            'release_strategy': 'standard',
            'status': 'pending',
            'approval_status': 'pending',
            'submitter': 'zhangsan',
            'change_summary': '管理后台生产发布申请',
            'description': '典型案例：待审批发布单',
            'docker_host': gateway_docker_env,
            'container_port': 8082,
            'service_port': 8082,
            'approval_flow': flow_prod,
            'deploy_log': '',
            'deploy_dir': '',
            'deployed_at': timezone.now() - timedelta(hours=1),
            'step_statuses': ['approved', 'pending', 'pending'],
        },
        {
            'app_name': 'member-center',
            'business_line': BIZ_DATA,
            'version': 'v2.4.1',
            'image': 'registry.demo.local/member-center:v2.4.1',
            'environment': 'prod',
            'deploy_mode': 'docker_compose',
            'release_strategy': 'standard',
            'status': 'failed',
            'approval_status': 'approved',
            'submitter': 'lisi',
            'deployer': 'ops-admin',
            'approver': 'ops-admin',
            'approval_comment': '允许按故障单重试',
            'change_summary': '会员中心生产发布失败示例',
            'description': '典型案例：执行失败发布单',
            'docker_host': gateway_docker_env,
            'container_port': 8090,
            'service_port': 8090,
            'approval_flow': flow_prod,
            'execution_count': 1,
            'is_current': False,
            'approved_at': timezone.now() - timedelta(hours=4, minutes=12),
            'executed_at': timezone.now() - timedelta(hours=4, minutes=10),
            'finished_at': timezone.now() - timedelta(hours=4, minutes=6),
            'deploy_dir': '/opt/agdevops/apps/member-center-prod',
            'deploy_log': '[INFO] 发布模式: Docker 环境\n[INFO] 发布策略: 标准发布\n[ERROR] 应用健康检查失败，已终止发布',
            'deployed_at': timezone.now() - timedelta(hours=4),
            'step_statuses': ['approved', 'approved', 'approved'],
        },
    ]

    for item in release_items:
        deployed_at = item.pop('deployed_at')
        step_statuses = item.pop('step_statuses')
        deployment = Deployment.objects.create(**item)
        Deployment.objects.filter(pk=deployment.pk).update(deployed_at=deployed_at)
        deployment.refresh_from_db()
        _create_approval_steps(deployment, step_statuses)


class Command(BaseCommand):
    help = '生成 Mock 演示数据'

    def handle(self, *args, **options):
        self.stdout.write('正在清除旧数据...')
        ServiceDeployment.objects.all().delete()
        DeploymentApprovalStep.objects.all().delete()
        DeploymentApprovalNode.objects.all().delete()
        DeploymentApprovalFlow.objects.all().delete()
        Deployment.objects.all().delete()
        Alert.objects.all().delete()
        LogEntry.objects.all().delete()
        Host.objects.all().delete()
        DockerHost.objects.all().delete()

        self.stdout.write('正在生成主机数据...')
        hosts = []
        host_configs = [
            {
                'hostname': 'order-api-ecs-01',
                'ip_address': '10.10.1.10',
                'os_type': 'Alibaba Cloud Linux 3',
                'business_line': BIZ_COMMERCE,
                'environment': 'prod',
                'admin_user': '应用运维-李俊',
                'description': '订单服务生产节点 A，对应 CMDB 云主机配置项',
                'status': 'online',
                'cpu_usage': 43.0,
                'memory_usage': 52.0,
                'disk_usage': 61.0,
            },
            {
                'hostname': 'order-api-ecs-02',
                'ip_address': '10.10.1.11',
                'os_type': 'Alibaba Cloud Linux 3',
                'business_line': BIZ_COMMERCE,
                'environment': 'prod',
                'admin_user': '应用运维-李俊',
                'description': '订单服务生产节点 B，对应 CMDB 云主机配置项',
                'status': 'online',
                'cpu_usage': 41.0,
                'memory_usage': 49.0,
                'disk_usage': 58.0,
            },
            {
                'hostname': 'order-perf-test-ecs',
                'ip_address': '10.10.20.10',
                'os_type': 'Ubuntu 22.04',
                'business_line': BIZ_COMMERCE,
                'environment': 'test',
                'admin_user': '测试平台-陈芳',
                'description': '压测环境主机，压测结束后应及时回收或降配',
                'status': 'warning',
                'cpu_usage': 12.0,
                'memory_usage': 28.0,
                'disk_usage': 46.0,
            },
            {
                'hostname': 'feature-x-dev-ecs',
                'ip_address': '10.10.30.30',
                'os_type': 'Ubuntu 22.04',
                'business_line': BIZ_COMMERCE,
                'environment': 'dev',
                'admin_user': '研发-张晨',
                'description': '功能联调开发主机，当前利用率偏低',
                'status': 'warning',
                'cpu_usage': 4.0,
                'memory_usage': 18.0,
                'disk_usage': 25.0,
            },
            {
                'hostname': 'airflow-worker-dev',
                'ip_address': '10.20.10.10',
                'os_type': 'CentOS Stream 9',
                'business_line': BIZ_DATA,
                'environment': 'dev',
                'admin_user': '数据平台-韩梅',
                'description': '开发调度节点，对应 CMDB 开发环境主机',
                'status': 'online',
                'cpu_usage': 14.0,
                'memory_usage': 32.0,
                'disk_usage': 37.0,
            },
            {
                'hostname': 'legacy-data-sync',
                'ip_address': '10.20.30.20',
                'os_type': 'CentOS 7.9',
                'business_line': BIZ_DATA,
                'environment': 'prod',
                'admin_user': '数据集成-孙博',
                'description': '遗留同步主机，已停止使用但仍未完成下线回收',
                'status': 'offline',
                'cpu_usage': 0.0,
                'memory_usage': 0.0,
                'disk_usage': 0.0,
            },
            {
                'hostname': 'k8s-node-01',
                'ip_address': '10.30.1.11',
                'os_type': 'Ubuntu 22.04',
                'business_line': BIZ_INFRA,
                'environment': 'prod',
                'admin_user': 'SRE-王涛',
                'description': '基础设施生产 K8s 工作节点，与 CMDB 配置项一致',
                'status': 'online',
                'cpu_usage': 28.0,
                'memory_usage': 44.0,
                'disk_usage': 51.0,
            },
        ]
        for config in host_configs:
            hosts.append(
                Host.objects.create(
                    hostname=config['hostname'],
                    ip_address=config['ip_address'],
                    os_type=config['os_type'],
                    business_line=config['business_line'],
                    environment=config['environment'],
                    admin_user=config['admin_user'],
                    description=config['description'],
                    status=config['status'],
                    cpu_usage=config['cpu_usage'],
                    memory_usage=config['memory_usage'],
                    disk_usage=config['disk_usage'],
                )
            )

        self.stdout.write('正在生成 Docker 环境数据...')
        docker_hosts = [
            DockerHost.objects.create(
                name='app-release-test',
                ip_address='192.168.1.120',
                ssh_port=22,
                ssh_user='root',
                ssh_password='',
                docker_api_version='24.0',
                status='connected',
                description='应用发布测试 Docker 环境',
            ),
            DockerHost.objects.create(
                name='gateway-prod',
                ip_address='192.168.1.121',
                ssh_port=22,
                ssh_user='root',
                ssh_password='',
                docker_api_version='24.0',
                status='connected',
                description='网关生产 Docker 环境',
            ),
            DockerHost.objects.create(
                name='member-prod',
                ip_address='192.168.1.122',
                ssh_port=22,
                ssh_user='root',
                ssh_password='',
                docker_api_version='24.0',
                status='connected',
                description='会员中心生产 Docker 环境',
            ),
        ]

        self.stdout.write('正在准备应用发布典型案例...')

        self.stdout.write('正在生成告警数据...')
        alert_templates = [
            ('CPU 使用率过高', 'critical', 'Prometheus', 'CPU 使用率持续 5 分钟超过 90%'),
            ('内存使用率过高', 'warning', 'Prometheus', '内存使用率超过 80%'),
            ('磁盘空间不足', 'critical', 'Zabbix', '磁盘使用率超过 95%，请及时清理'),
            ('服务响应超时', 'warning', 'APM', '服务平均响应时间超过 3 秒'),
        ]
        for _ in range(12):
            title, level, source, message = random.choice(alert_templates)
            Alert.objects.create(
                title=title,
                level=level,
                source=source,
                message=message,
                is_acknowledged=random.choice([True, False, False]),
                host=random.choice(hosts),
            )

        self.stdout.write('正在生成日志数据...')
        services = ['user-service', 'order-service', 'gateway', 'nginx', 'mysql', 'redis']
        log_messages = {
            'error': ['Connection refused to database', 'Timeout while waiting for response'],
            'warning': ['Slow query detected: 2.5s', 'Connection pool reaching limit'],
            'info': ['Service started successfully', 'Health check passed'],
            'debug': ['Cache hit for key: user_123', 'WebSocket connection established'],
        }
        for _ in range(40):
            level = random.choices(['error', 'warning', 'info', 'debug'], weights=[10, 20, 50, 20])[0]
            LogEntry.objects.create(
                level=level,
                service=random.choice(services),
                message=random.choice(log_messages[level]),
                host=random.choice(hosts),
            )

        seed_app_release_demo(self.stdout, hosts, docker_hosts)
        self.stdout.write(
            self.style.SUCCESS(
                f'数据生成完成: {Host.objects.count()} 主机, {Deployment.objects.count()} 发布记录, '
                f'{Alert.objects.count()} 告警, {LogEntry.objects.count()} 日志'
            )
        )

        self.stdout.write('正在生成 RBAC 演示账号...')
        seed_marketplace_demo(self.stdout, hosts)
        call_command('seed_rbac_demo')

        self.stdout.write('正在生成 CMDB 演示数据...')
        seed_cmdb_demo(self.stdout)
        sync_current_deployments_to_cmdb()
