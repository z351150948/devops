from rest_framework import serializers

from cmdb.models import CIRelation, ConfigItem, ResourceNode

from .models import (
    Alert,
    Deployment,
    DeploymentApprovalFlow,
    DeploymentApprovalNode,
    DeploymentApprovalStep,
    DockerHost,
    Host,
    K8sCluster,
    LogDataSource,
    LogEntry,
    NginxCertificate,
    NginxDomain,
    NginxEnvironment,
    NginxRoute,
)

LOG_SENSITIVE_KEYS = {
    'password',
    'api_key',
    'token',
    'bearer_token',
    'access_key_id',
    'access_key_secret',
}


class HostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Host
        fields = '__all__'


class DeploymentApprovalNodeSerializer(serializers.ModelSerializer):
    approver_type_display = serializers.CharField(source='get_approver_type_display', read_only=True)
    approver_scope_display = serializers.CharField(read_only=True)

    class Meta:
        model = DeploymentApprovalNode
        fields = [
            'id',
            'name',
            'order',
            'approver_type',
            'approver_type_display',
            'approver_value',
            'approver_scope_display',
            'description',
        ]


class DeploymentApprovalStepSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    approver_type_display = serializers.CharField(source='get_approver_type_display', read_only=True)
    approver_scope_display = serializers.CharField(read_only=True)

    class Meta:
        model = DeploymentApprovalStep
        fields = [
            'id',
            'flow',
            'node_name',
            'node_order',
            'approver_type',
            'approver_type_display',
            'approver_value',
            'approver_scope_display',
            'status',
            'status_display',
            'is_current',
            'approver',
            'comment',
            'acted_at',
            'created_at',
        ]


class DeploymentApprovalFlowSerializer(serializers.ModelSerializer):
    environment_display = serializers.SerializerMethodField()
    scope_display = serializers.CharField(read_only=True)
    nodes = DeploymentApprovalNodeSerializer(many=True)
    node_count = serializers.SerializerMethodField()

    class Meta:
        model = DeploymentApprovalFlow
        fields = [
            'id',
            'name',
            'environment',
            'environment_display',
            'scope_display',
            'description',
            'is_active',
            'created_by',
            'node_count',
            'nodes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

    def get_environment_display(self, obj):
        return obj.get_environment_display() if obj.environment else '全部环境'

    def get_node_count(self, obj):
        return obj.nodes.count()

    def validate_nodes(self, value):
        if not value:
            raise serializers.ValidationError('至少需要配置一个审批节点')
        orders = [item.get('order') for item in value]
        if len(set(orders)) != len(orders):
            raise serializers.ValidationError('审批节点顺序不能重复')
        for item in value:
            if not item.get('name'):
                raise serializers.ValidationError('审批节点名称不能为空')
        return value

    def _sync_active_flow(self, instance):
        if instance.is_active:
            DeploymentApprovalFlow.objects.filter(
                environment=instance.environment,
                is_active=True,
            ).exclude(pk=instance.pk).update(is_active=False)

    def _replace_nodes(self, instance, nodes):
        instance.nodes.all().delete()
        DeploymentApprovalNode.objects.bulk_create([
            DeploymentApprovalNode(
                flow=instance,
                name=item['name'],
                order=item['order'],
                approver_type=item.get('approver_type') or 'user',
                approver_value=item.get('approver_value', ''),
                description=item.get('description', ''),
            )
            for item in sorted(nodes, key=lambda data: (data['order'], data.get('name', '')))
        ])

    def create(self, validated_data):
        nodes = validated_data.pop('nodes', [])
        instance = super().create(validated_data)
        self._replace_nodes(instance, nodes)
        self._sync_active_flow(instance)
        return instance

    def update(self, instance, validated_data):
        nodes = validated_data.pop('nodes', None)
        instance = super().update(instance, validated_data)
        if nodes is not None:
            self._replace_nodes(instance, nodes)
        self._sync_active_flow(instance)
        return instance


class DeploymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    deploy_mode_display = serializers.CharField(source='get_deploy_mode_display', read_only=True)
    approval_status_display = serializers.CharField(source='get_approval_status_display', read_only=True)
    action_type_display = serializers.CharField(source='get_action_type_display', read_only=True)
    release_strategy_display = serializers.CharField(source='get_release_strategy_display', read_only=True)
    docker_host_name = serializers.CharField(source='docker_host.name', read_only=True, default='')
    docker_host_ip = serializers.CharField(source='docker_host.ip_address', read_only=True, default='')
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')
    host_ip = serializers.CharField(source='host.ip_address', read_only=True, default='')
    cluster_name = serializers.CharField(source='cluster.name', read_only=True, default='')
    target_display = serializers.CharField(read_only=True)
    strategy_summary = serializers.CharField(read_only=True)
    approval_progress_text = serializers.CharField(read_only=True)
    approval_flow_name = serializers.CharField(source='approval_flow.name', read_only=True, default='')
    approval_steps = DeploymentApprovalStepSerializer(many=True, read_only=True)
    current_approval_step = serializers.SerializerMethodField()
    previous_success_version = serializers.CharField(source='previous_success.version', read_only=True, default='')
    rollback_source_version = serializers.CharField(source='rollback_source.version', read_only=True, default='')
    rerun_source_version = serializers.CharField(source='rerun_source.version', read_only=True, default='')
    can_rollback = serializers.SerializerMethodField()
    can_advance_batch = serializers.SerializerMethodField()
    cmdb_item_id = serializers.SerializerMethodField()
    cmdb_item_name = serializers.SerializerMethodField()
    cmdb_item_status = serializers.SerializerMethodField()
    cmdb_targets = serializers.SerializerMethodField()

    class Meta:
        model = Deployment
        fields = [
            'id',
            'app_name',
            'business_line',
            'version',
            'image',
            'environment',
            'environment_display',
            'deploy_mode',
            'deploy_mode_display',
            'status',
            'status_display',
            'approval_status',
            'approval_status_display',
            'action_type',
            'action_type_display',
            'release_strategy',
            'release_strategy_display',
            'strategy_summary',
            'canary_percent',
            'batch_total',
            'batch_current',
            'batch_size',
            'strategy_config',
            'submitter',
            'deployer',
            'approver',
            'approval_comment',
            'change_summary',
            'description',
            'env_config',
            'deploy_log',
            'deploy_dir',
            'release_name',
            'namespace',
            'replicas',
            'container_port',
            'service_port',
            'docker_host',
            'docker_host_name',
            'docker_host_ip',
            'host',
            'host_name',
            'host_ip',
            'cluster',
            'cluster_name',
            'target_display',
            'approval_flow',
            'approval_flow_name',
            'approval_progress_text',
            'approval_steps',
            'current_approval_step',
            'previous_success',
            'previous_success_version',
            'rollback_source',
            'rollback_source_version',
            'rerun_source',
            'rerun_source_version',
            'approved_at',
            'executed_at',
            'finished_at',
            'execution_count',
            'is_current',
            'can_rollback',
            'can_advance_batch',
            'cmdb_item_id',
            'cmdb_item_name',
            'cmdb_item_status',
            'cmdb_targets',
            'deployed_at',
        ]
        read_only_fields = [
            'status',
            'approval_status',
            'action_type',
            'submitter',
            'deployer',
            'approver',
            'approval_comment',
            'deploy_log',
            'deploy_dir',
            'approval_flow',
            'previous_success',
            'rollback_source',
            'rerun_source',
            'approved_at',
            'executed_at',
            'finished_at',
            'execution_count',
            'is_current',
            'batch_current',
            'deployed_at',
        ]

    def get_can_rollback(self, obj):
        return bool(obj.is_current and obj.get_previous_successful_release())

    def get_can_advance_batch(self, obj):
        return bool(
            obj.release_strategy == 'batch'
            and obj.approval_status == 'approved'
            and obj.is_current
            and (obj.batch_current or 0) < (obj.batch_total or 1)
        )

    def get_current_approval_step(self, obj):
        step = obj.current_approval_step
        return DeploymentApprovalStepSerializer(step).data if step else None

    def _get_cmdb_item(self, obj):
        cached = getattr(obj, '_cmdb_item_cache', None)
        if cached is not None:
            return cached
        item = ConfigItem.objects.filter(
            attributes__source='app_release',
            attributes__deployment_id=obj.id,
        ).first()
        setattr(obj, '_cmdb_item_cache', item)
        return item

    def get_cmdb_item_id(self, obj):
        item = self._get_cmdb_item(obj)
        return item.id if item else None

    def get_cmdb_item_name(self, obj):
        item = self._get_cmdb_item(obj)
        return item.name if item else ''

    def get_cmdb_item_status(self, obj):
        item = self._get_cmdb_item(obj)
        return item.get_status_display() if item else ''

    def get_cmdb_targets(self, obj):
        item = self._get_cmdb_item(obj)
        if not item:
            return []
        return [
            relation.target.name
            for relation in CIRelation.objects.select_related('target').filter(source=item, relation_type='runs_on')
        ]

    def validate_strategy_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('策略配置必须为 JSON 对象')
        return value

    def validate_env_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('环境变量必须为 JSON 对象')
        return value

    def validate(self, attrs):
        business_line = (attrs.get('business_line') or getattr(self.instance, 'business_line', '') or '').strip()
        environment = attrs.get('environment') or getattr(self.instance, 'environment', '')
        deploy_mode = attrs.get('deploy_mode') or getattr(self.instance, 'deploy_mode', 'docker_compose')
        docker_host = attrs.get('docker_host', getattr(self.instance, 'docker_host', None))
        host = attrs.get('host', getattr(self.instance, 'host', None))
        cluster = attrs.get('cluster', getattr(self.instance, 'cluster', None))
        namespace = attrs.get('namespace', getattr(self.instance, 'namespace', ''))
        strategy = attrs.get('release_strategy') or getattr(self.instance, 'release_strategy', 'standard')
        canary_percent = attrs.get('canary_percent', getattr(self.instance, 'canary_percent', 10))
        batch_total = attrs.get('batch_total', getattr(self.instance, 'batch_total', 1))
        batch_size = attrs.get('batch_size', getattr(self.instance, 'batch_size', 1))

        if not business_line:
            raise serializers.ValidationError({'business_line': '请选择业务线'})
        biz_node = ResourceNode.objects.filter(node_type='biz', name=business_line).first()
        if not biz_node:
            raise serializers.ValidationError({'business_line': '所选业务线未在 CMDB 资源树中配置'})
        if not environment:
            raise serializers.ValidationError({'environment': '请选择环境'})
        if not ResourceNode.objects.filter(node_type='env', parent=biz_node, name=environment).exists():
            raise serializers.ValidationError({'environment': '所选环境未在 CMDB 中绑定到当前业务线'})
        attrs['business_line'] = business_line

        if deploy_mode == 'docker_compose':
            docker_host = docker_host or self._resolve_docker_host_from_legacy(host)
            if not docker_host:
                raise serializers.ValidationError({'docker_host': 'Docker 环境模式必须选择 Docker 环境'})
            attrs['docker_host'] = docker_host
            attrs['host'] = None
            attrs['cluster'] = None
            attrs['namespace'] = ''
        else:
            if not cluster:
                raise serializers.ValidationError({'cluster': 'K8s 集群模式必须选择目标集群'})
            attrs['docker_host'] = None
            attrs['host'] = None
            attrs['namespace'] = (namespace or 'default').strip() or 'default'

        if strategy == 'canary':
            if canary_percent <= 0 or canary_percent > 100:
                raise serializers.ValidationError({'canary_percent': '灰度比例必须在 1-100 之间'})
            attrs['batch_total'] = 1
            attrs['batch_size'] = 1
        elif strategy == 'batch':
            if batch_total < 2:
                raise serializers.ValidationError({'batch_total': '批次发布至少需要 2 个批次'})
            if batch_size < 1:
                raise serializers.ValidationError({'batch_size': '单批规模必须大于 0'})
        else:
            attrs['canary_percent'] = 10
            attrs['batch_total'] = 1
            attrs['batch_size'] = 1

        image = attrs.get('image') or getattr(self.instance, 'image', '')
        app_name = attrs.get('app_name') or getattr(self.instance, 'app_name', '')
        version = attrs.get('version') or getattr(self.instance, 'version', '')
        if not image:
            attrs['image'] = f'{app_name}:{version}'
        return attrs

    def _resolve_docker_host_from_legacy(self, host):
        if not host:
            return None
        docker_host = DockerHost.objects.filter(ip_address=host.ip_address).order_by('id').first()
        if docker_host:
            return docker_host
        docker_host = DockerHost.objects.filter(name=host.hostname).order_by('id').first()
        if docker_host:
            return docker_host
        status_map = {
            'online': 'connected',
            'offline': 'disconnected',
            'warning': 'error',
        }
        return DockerHost.objects.create(
            name=host.hostname,
            ip_address=host.ip_address,
            ssh_port=getattr(host, 'ssh_port', 22) or 22,
            ssh_user=getattr(host, 'ssh_user', 'root') or 'root',
            ssh_password=getattr(host, 'ssh_password', '') or '',
            status=status_map.get(getattr(host, 'status', ''), 'disconnected'),
            description='由应用发布主机目标自动映射',
        )


class ApprovalActionSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class DeploymentActionSerializer(serializers.Serializer):
    change_summary = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class AlertSerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = Alert
        fields = '__all__'


class LogEntrySerializer(serializers.ModelSerializer):
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = LogEntry
        fields = '__all__'


class LogDataSourceSerializer(serializers.ModelSerializer):
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)

    class Meta:
        model = LogDataSource
        fields = '__all__'

    def validate_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('config 必须是对象')
        return value

    def validate(self, attrs):
        provider = attrs.get('provider') or getattr(self.instance, 'provider', None)
        config = dict(getattr(self.instance, 'config', {}) or {})
        incoming = attrs.get('config', {})

        for key, value in incoming.items():
            if key in LOG_SENSITIVE_KEYS and value in ('', None, 'configured'):
                if self.instance and key in config:
                    continue
                config.pop(key, None)
                continue
            config[key] = value

        attrs['config'] = config
        return attrs

    def _sync_default(self, instance):
        if instance.is_default:
            LogDataSource.objects.filter(provider=instance.provider, is_default=True).exclude(pk=instance.pk).update(
                is_default=False
            )

    def create(self, validated_data):
        instance = super().create(validated_data)
        self._sync_default(instance)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        self._sync_default(instance)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        masked = {}
        is_demo = bool((instance.config or {}).get('demo_mode'))
        for key, value in (instance.config or {}).items():
            if key in LOG_SENSITIVE_KEYS and not is_demo:
                masked[key] = 'configured' if value else ''
            else:
                masked[key] = value
        data['config'] = masked
        return data


class K8sClusterSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = K8sCluster
        fields = '__all__'
        extra_kwargs = {
            'kubeconfig': {'write_only': True},
        }


class DockerHostSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = DockerHost
        fields = '__all__'
        extra_kwargs = {
            'ssh_password': {'write_only': True},
        }


class NginxEnvironmentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = NginxEnvironment
        fields = '__all__'
        extra_kwargs = {
            'ssh_password': {'write_only': True},
        }


class NginxCertificateSerializer(serializers.ModelSerializer):
    environment_names = serializers.SerializerMethodField()

    class Meta:
        model = NginxCertificate
        fields = '__all__'
        extra_kwargs = {
            'domain': {'read_only': True},
            'expires_at': {'read_only': True},
            'cert_content': {'write_only': True},
            'key_content': {'write_only': True},
        }

    def get_environment_names(self, obj):
        return [{'id': item.id, 'name': item.name} for item in obj.environments.all()]


class NginxDomainSerializer(serializers.ModelSerializer):
    environment_name = serializers.CharField(source='environment.name', read_only=True)
    ssl_enabled = serializers.BooleanField(read_only=True)
    certificate_domain = serializers.CharField(source='certificate.domain', read_only=True, default=None)

    class Meta:
        model = NginxDomain
        fields = '__all__'


class NginxRouteSerializer(serializers.ModelSerializer):
    domain_name = serializers.CharField(source='nginx_domain.domain', read_only=True)
    environment_name = serializers.CharField(source='nginx_domain.environment.name', read_only=True)

    class Meta:
        model = NginxRoute
        fields = '__all__'
