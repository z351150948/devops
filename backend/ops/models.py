from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.text import slugify


class Host(models.Model):
    ENV_CHOICES = [
        ('prod', '生产'),
        ('test', '测试'),
        ('dev', '开发'),
    ]

    STATUS_CHOICES = [
        ('online', '在线'),
        ('offline', '离线'),
        ('warning', '告警'),
    ]

    hostname = models.CharField('主机名', max_length=128, unique=True)
    ip_address = models.GenericIPAddressField('IP 地址')
    business_line = models.CharField('业务线', max_length=50, blank=True, default='')
    environment = models.CharField('环境', max_length=20, choices=ENV_CHOICES, blank=True, default='')
    admin_user = models.CharField('负责人', max_length=50, blank=True, default='')
    os_type = models.CharField('操作系统', max_length=64, default='Linux')
    description = models.CharField('描述', max_length=200, blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='online')
    cpu_usage = models.FloatField('CPU 使用率(%)', default=0)
    memory_usage = models.FloatField('内存使用率(%)', default=0)
    disk_usage = models.FloatField('磁盘使用率(%)', default=0)
    ssh_port = models.IntegerField('SSH 端口', default=22)
    ssh_user = models.CharField('SSH 用户', max_length=64, default='root')
    ssh_password = models.CharField('SSH 密码', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '主机'
        verbose_name_plural = '主机'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.hostname} ({self.ip_address})'


class Deployment(models.Model):
    DEPLOY_MODE_CHOICES = [
        ('docker_compose', 'Docker 环境'),
        ('k8s', 'K8s 集群'),
    ]
    STATUS_CHOICES = [
        ('pending', '待执行'),
        ('rejected', '已驳回'),
        ('deploying', '发布中'),
        ('running', '运行中'),
        ('stopped', '已停止'),
        ('failed', '发布失败'),
        ('removed', '已下线'),
    ]
    APPROVAL_STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]
    ACTION_TYPE_CHOICES = [
        ('deploy', '应用发布'),
        ('rollback', '版本回滚'),
        ('rerun', '重新执行'),
    ]
    RELEASE_STRATEGY_CHOICES = [
        ('standard', '标准发布'),
        ('canary', '灰度发布'),
        ('batch', '批次发布'),
    ]
    ENV_CHOICES = [
        ('prod', '生产'),
        ('test', '测试'),
        ('dev', '开发'),
    ]

    app_name = models.CharField('应用名称', max_length=128)
    business_line = models.CharField('业务线', max_length=50, blank=True, default='')
    version = models.CharField('版本号', max_length=64)
    image = models.CharField('镜像地址', max_length=255, blank=True, default='')
    environment = models.CharField('环境', max_length=32, choices=ENV_CHOICES, default='test')
    deploy_mode = models.CharField('发布模式', max_length=32, choices=DEPLOY_MODE_CHOICES, default='docker_compose')
    status = models.CharField('执行状态', max_length=16, choices=STATUS_CHOICES, default='pending')
    approval_status = models.CharField('审批状态', max_length=16, choices=APPROVAL_STATUS_CHOICES, default='pending')
    action_type = models.CharField('发布类型', max_length=16, choices=ACTION_TYPE_CHOICES, default='deploy')
    release_strategy = models.CharField('发布策略', max_length=16, choices=RELEASE_STRATEGY_CHOICES, default='standard')
    submitter = models.CharField('申请人', max_length=64, default='admin')
    deployer = models.CharField('执行人', max_length=64, blank=True, default='')
    approver = models.CharField('审批人', max_length=64, blank=True, default='')
    approval_comment = models.CharField('审批意见', max_length=255, blank=True, default='')
    change_summary = models.CharField('变更说明', max_length=255, blank=True, default='')
    description = models.TextField('描述', blank=True, default='')
    env_config = models.JSONField('环境变量', default=dict, blank=True)
    deploy_log = models.TextField('发布日志', blank=True, default='')
    deploy_dir = models.CharField('发布目录', max_length=256, blank=True, default='')
    release_name = models.CharField('发布名称', max_length=128, blank=True, default='')
    namespace = models.CharField('命名空间', max_length=128, blank=True, default='')
    replicas = models.PositiveIntegerField('副本数', default=1)
    container_port = models.PositiveIntegerField('容器端口', null=True, blank=True)
    service_port = models.PositiveIntegerField('服务端口', null=True, blank=True)
    canary_percent = models.PositiveIntegerField(
        '灰度比例',
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )
    batch_total = models.PositiveIntegerField('批次总数', default=1)
    batch_current = models.PositiveIntegerField('当前批次', default=0)
    batch_size = models.PositiveIntegerField('单批规模', default=1)
    strategy_config = models.JSONField('策略配置', default=dict, blank=True)
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='目标主机')
    docker_host = models.ForeignKey(
        'DockerHost',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deployments',
        verbose_name='Docker 环境',
    )
    cluster = models.ForeignKey('K8sCluster', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='目标集群')
    approval_flow = models.ForeignKey(
        'DeploymentApprovalFlow',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deployments',
        verbose_name='审批流程',
    )
    previous_success = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='followup_releases',
        verbose_name='上一成功版本',
    )
    rollback_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rollback_requests',
        verbose_name='回滚来源',
    )
    rerun_source = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rerun_requests',
        verbose_name='重试来源',
    )
    approved_at = models.DateTimeField('审批时间', null=True, blank=True)
    executed_at = models.DateTimeField('执行时间', null=True, blank=True)
    finished_at = models.DateTimeField('完成时间', null=True, blank=True)
    execution_count = models.PositiveIntegerField('执行次数', default=0)
    is_current = models.BooleanField('当前生效版本', default=False)
    deployed_at = models.DateTimeField('发布时间', auto_now_add=True)

    class Meta:
        verbose_name = '应用发布'
        verbose_name_plural = '应用发布'
        ordering = ['-deployed_at']
        indexes = [
            models.Index(fields=['approval_status', 'status']),
            models.Index(fields=['business_line', 'app_name', 'environment', 'deployed_at']),
            models.Index(fields=['is_current', 'deploy_mode']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['business_line', 'app_name', 'environment', 'docker_host'],
                condition=Q(deploy_mode='docker_compose', is_current=True),
                name='uniq_ops_curr_biz_app_docker_host',
            ),
            models.UniqueConstraint(
                fields=['business_line', 'app_name', 'environment', 'cluster', 'namespace'],
                condition=Q(deploy_mode='k8s', is_current=True),
                name='uniq_ops_curr_biz_app_k8s',
            ),
        ]

    def __str__(self):
        return f'{self.app_name} v{self.version} -> {self.environment}'

    @property
    def docker_target(self):
        return self.docker_host or self.host

    @property
    def target_display(self):
        if self.deploy_mode == 'k8s' and self.cluster_id:
            return f'{self.cluster.name} / {self.namespace or "default"}'
        target = self.docker_target
        if target:
            return getattr(target, 'name', '') or getattr(target, 'hostname', '') or '-'
        return '-'

    @property
    def release_name_display(self):
        return self.release_name or slugify(self.app_name) or self.app_name

    @property
    def strategy_summary(self):
        if self.release_strategy == 'canary':
            return f'灰度发布 {self.canary_percent}%'
        if self.release_strategy == 'batch':
            current = min(self.batch_current or 0, self.batch_total or 1)
            return f'批次发布 {current}/{self.batch_total or 1} 批'
        return '标准发布'

    @property
    def approval_progress_text(self):
        steps = list(self.approval_steps.all())
        if not steps:
            return '默认审批'
        approved_count = sum(1 for step in steps if step.status == 'approved')
        return f'{approved_count}/{len(steps)} 节点已完成'

    @property
    def current_approval_step(self):
        current = self.approval_steps.filter(is_current=True).order_by('node_order').first()
        if current:
            return current
        return self.approval_steps.filter(status='pending').order_by('node_order').first()

    def same_target_queryset(self):
        queryset = Deployment.objects.filter(
            business_line=self.business_line,
            app_name=self.app_name,
            environment=self.environment,
            deploy_mode=self.deploy_mode,
        )
        if self.deploy_mode == 'k8s':
            return queryset.filter(cluster=self.cluster, namespace=self.namespace or 'default')
        if self.docker_host_id:
            return queryset.filter(docker_host=self.docker_host)
        if self.host_id:
            return queryset.filter(host=self.host)
        return queryset.filter(pk=self.pk)

    def get_previous_successful_release(self):
        return self.same_target_queryset().filter(
            approval_status='approved',
            execution_count__gt=0,
            status__in=('running', 'stopped', 'removed'),
        ).exclude(pk=self.pk).order_by('-executed_at', '-id').first()


class DeploymentApprovalFlow(models.Model):
    ENV_CHOICES = [('', '全部环境')] + Deployment.ENV_CHOICES

    name = models.CharField('流程名称', max_length=128)
    environment = models.CharField('适用环境', max_length=32, choices=ENV_CHOICES, blank=True, default='')
    description = models.CharField('描述', max_length=255, blank=True, default='')
    is_active = models.BooleanField('启用', default=True)
    created_by = models.CharField('维护人', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '发布审批流程'
        verbose_name_plural = '发布审批流程'
        ordering = ['environment', 'name', '-updated_at']

    def __str__(self):
        return self.name

    @property
    def scope_display(self):
        return self.get_environment_display() if self.environment else '全部环境'


class DeploymentApprovalNode(models.Model):
    APPROVER_TYPE_CHOICES = [
        ('user', '指定用户'),
        ('role', '指定角色'),
        ('group', '指定用户组'),
    ]

    flow = models.ForeignKey(
        DeploymentApprovalFlow,
        on_delete=models.CASCADE,
        related_name='nodes',
        verbose_name='所属流程',
    )
    name = models.CharField('节点名称', max_length=128)
    order = models.PositiveIntegerField('排序', default=1)
    approver_type = models.CharField('审批人类型', max_length=16, choices=APPROVER_TYPE_CHOICES, default='user')
    approver_value = models.CharField('审批人值', max_length=128, blank=True, default='')
    description = models.CharField('节点说明', max_length=255, blank=True, default='')

    class Meta:
        verbose_name = '审批流程节点'
        verbose_name_plural = '审批流程节点'
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['flow', 'order'], name='uniq_ops_deploy_approval_flow_node_order'),
        ]

    def __str__(self):
        return f'{self.flow.name} - {self.name}'

    @property
    def approver_scope_display(self):
        return f'{self.get_approver_type_display()}: {self.approver_value or "-"}'


class DeploymentApprovalStep(models.Model):
    STEP_STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]

    deployment = models.ForeignKey(
        Deployment,
        on_delete=models.CASCADE,
        related_name='approval_steps',
        verbose_name='发布单',
    )
    flow = models.ForeignKey(
        DeploymentApprovalFlow,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='steps',
        verbose_name='审批流程',
    )
    node_name = models.CharField('节点名称', max_length=128)
    node_order = models.PositiveIntegerField('节点排序', default=1)
    approver_type = models.CharField(
        '审批人类型',
        max_length=16,
        choices=DeploymentApprovalNode.APPROVER_TYPE_CHOICES,
        default='user',
    )
    approver_value = models.CharField('审批人值', max_length=128, blank=True, default='')
    status = models.CharField('节点状态', max_length=16, choices=STEP_STATUS_CHOICES, default='pending')
    is_current = models.BooleanField('当前节点', default=False)
    approver = models.CharField('审批人', max_length=64, blank=True, default='')
    comment = models.CharField('审批意见', max_length=255, blank=True, default='')
    acted_at = models.DateTimeField('处理时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '发布审批步骤'
        verbose_name_plural = '发布审批步骤'
        ordering = ['node_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['deployment', 'node_order'], name='uniq_ops_deploy_approval_step_order'),
        ]
        indexes = [
            models.Index(fields=['deployment', 'status', 'is_current']),
        ]

    def __str__(self):
        return f'#{self.deployment_id} - {self.node_name}'

    @property
    def approver_scope_display(self):
        return f'{self.get_approver_type_display()}: {self.approver_value or "-"}'


class Alert(models.Model):
    LEVEL_CHOICES = [
        ('critical', '严重'),
        ('warning', '警告'),
        ('info', '信息'),
    ]

    title = models.CharField('告警标题', max_length=256)
    level = models.CharField('级别', max_length=16, choices=LEVEL_CHOICES, default='info')
    source = models.CharField('来源', max_length=128)
    message = models.TextField('详情')
    is_acknowledged = models.BooleanField('已确认', default=False)
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='关联主机')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '告警'
        verbose_name_plural = '告警'
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.level}] {self.title}'


class LogEntry(models.Model):
    LEVEL_CHOICES = [
        ('error', 'ERROR'),
        ('warning', 'WARNING'),
        ('info', 'INFO'),
        ('debug', 'DEBUG'),
    ]

    level = models.CharField('级别', max_length=16, choices=LEVEL_CHOICES, default='info')
    service = models.CharField('服务名', max_length=128)
    message = models.TextField('日志内容')
    host = models.ForeignKey(Host, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='来源主机')
    timestamp = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        verbose_name = '日志'
        verbose_name_plural = '日志'
        ordering = ['-timestamp']

    def __str__(self):
        return f'[{self.level}] {self.service}: {self.message[:50]}'


class LogDataSource(models.Model):
    PROVIDER_CHOICES = [
        ('loki', 'Loki'),
        ('elk', 'ELK / Elasticsearch'),
        ('sls', '阿里云 SLS'),
    ]

    name = models.CharField('名称', max_length=128, unique=True)
    provider = models.CharField('日志类型', max_length=16, choices=PROVIDER_CHOICES)
    description = models.CharField('描述', max_length=255, blank=True, default='')
    config = models.JSONField('连接配置', default=dict, blank=True)
    is_enabled = models.BooleanField('启用', default=True)
    is_default = models.BooleanField('默认数据源', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '日志数据源'
        verbose_name_plural = '日志数据源'
        ordering = ['provider', 'name']

    def __str__(self):
        return f'{self.get_provider_display()} - {self.name}'


class K8sCluster(models.Model):
    STATUS_CHOICES = [
        ('connected', '已连接'),
        ('disconnected', '未连接'),
        ('error', '异常'),
    ]

    name = models.CharField('集群名称', max_length=128, unique=True)
    api_server = models.CharField('API Server', max_length=256, blank=True, default='')
    kubeconfig = models.TextField('KubeConfig', help_text='YAML 格式的 kubeconfig 内容')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='disconnected')
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'K8s 集群'
        verbose_name_plural = 'K8s 集群'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class K8sConfigRevision(models.Model):
    ACTION_CHOICES = [
        ('update', 'Update Snapshot'),
        ('rollback', 'Rollback Snapshot'),
    ]

    cluster = models.ForeignKey(K8sCluster, on_delete=models.CASCADE, related_name='config_revisions')
    resource_type = models.CharField(max_length=32)
    namespace = models.CharField(max_length=128)
    resource_name = models.CharField(max_length=255)
    secret_type = models.CharField(max_length=128, blank=True, default='')
    content = models.TextField()
    operator = models.CharField(max_length=64, blank=True, default='')
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, default='update')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'K8s config revision'
        verbose_name_plural = 'K8s config revisions'
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['cluster', 'resource_type', 'namespace', 'resource_name']),
        ]

    def __str__(self):
        return f'{self.cluster.name}:{self.resource_type}/{self.namespace}/{self.resource_name}'


class DockerHost(models.Model):
    STATUS_CHOICES = [
        ('connected', '已连接'),
        ('disconnected', '未连接'),
        ('error', '异常'),
    ]

    name = models.CharField('环境名称', max_length=128, unique=True)
    ip_address = models.GenericIPAddressField('IP 地址')
    ssh_port = models.IntegerField('SSH 端口', default=22)
    ssh_user = models.CharField('SSH 用户', max_length=64, default='root')
    ssh_password = models.CharField('SSH 密码', max_length=256, blank=True, default='')
    docker_api_version = models.CharField('Docker API 版本', max_length=16, blank=True, default='')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='disconnected')
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Docker 环境'
        verbose_name_plural = 'Docker 环境'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.ip_address})'


class NginxEnvironment(models.Model):
    STATUS_CHOICES = [
        ('connected', '已连接'),
        ('disconnected', '未连接'),
        ('error', '异常'),
    ]

    name = models.CharField('环境名称', max_length=128, unique=True)
    ip_address = models.GenericIPAddressField('IP 地址')
    ssh_port = models.IntegerField('SSH 端口', default=22)
    ssh_user = models.CharField('SSH 用户', max_length=64, default='root')
    ssh_password = models.CharField('SSH 密码', max_length=256, blank=True, default='')
    nginx_path = models.CharField('Nginx 路径', max_length=256, default='/etc/nginx')
    status = models.CharField('状态', max_length=16, choices=STATUS_CHOICES, default='disconnected')
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 环境'
        verbose_name_plural = 'Nginx 环境'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.ip_address})'


class NginxCertificate(models.Model):
    domain = models.CharField('证书域名', max_length=256, help_text='证书对应的域名')
    cert_content = models.TextField('证书内容 (PEM)', blank=True, default='')
    key_content = models.TextField('私钥内容 (KEY)', blank=True, default='')
    environments = models.ManyToManyField(
        NginxEnvironment,
        blank=True,
        verbose_name='关联环境',
        related_name='certificates',
    )
    expires_at = models.DateTimeField('过期时间', null=True, blank=True)
    description = models.CharField('描述', max_length=256, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 证书'
        verbose_name_plural = 'Nginx 证书'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.domain}'

    @property
    def cert_filename(self):
        safe = self.domain.replace('*', '_wc_').replace('.', '_')
        return f'{safe}.pem'

    @property
    def key_filename(self):
        safe = self.domain.replace('*', '_wc_').replace('.', '_')
        return f'{safe}.key'


class NginxDomain(models.Model):
    environment = models.ForeignKey(
        NginxEnvironment,
        on_delete=models.CASCADE,
        verbose_name='所属环境',
        related_name='domains',
    )
    domain = models.CharField('域名/IP', max_length=256, help_text='填写域名或 IP 地址')
    listen_port = models.IntegerField('监听端口', default=80)
    ssl_port = models.IntegerField('SSL 端口', default=443)
    certificate = models.ForeignKey(
        NginxCertificate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='关联证书',
        related_name='linked_domains',
    )
    enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 域名'
        verbose_name_plural = 'Nginx 域名'
        ordering = ['-created_at']
        unique_together = ('environment', 'domain', 'listen_port')

    def __str__(self):
        return f'{self.domain}:{self.listen_port} ({self.environment.name})'

    @property
    def ssl_enabled(self):
        return self.certificate is not None and self.certificate_id is not None

    @property
    def conf_filename(self):
        safe = self.domain.replace('*', '_wc_').replace('.', '_')
        return f'{safe}_{self.listen_port}.conf'


class NginxRoute(models.Model):
    nginx_domain = models.ForeignKey(
        NginxDomain,
        on_delete=models.CASCADE,
        verbose_name='所属域名',
        related_name='routes',
    )
    location = models.CharField('Location 路径', max_length=256, default='/')
    upstream_servers = models.TextField(
        '后端地址',
        blank=True,
        default='',
        help_text='每行一个后端地址，如 http://127.0.0.1:8080',
    )
    redirect_url = models.CharField('重定向地址', max_length=512, blank=True, default='')
    redirect_code = models.IntegerField('重定向状态码', default=301)
    custom_headers = models.TextField(
        '自定义 Header (JSON)',
        blank=True,
        default='',
        help_text='[{"name":"X-Custom","value":"val"}]',
    )
    proxy_set_headers = models.TextField(
        'proxy_set_header (JSON)',
        blank=True,
        default='',
        help_text='[{"name":"Host","value":"$host"}]',
    )
    client_max_body_size = models.CharField('上传大小限制', max_length=32, blank=True, default='10m')
    extra_directives = models.TextField(
        '额外指令',
        blank=True,
        default='',
        help_text='原始 Nginx 指令，每行一条',
    )
    enabled = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'Nginx 路由'
        verbose_name_plural = 'Nginx 路由'
        ordering = ['-created_at']
        unique_together = ('nginx_domain', 'location')

    def __str__(self):
        return f'{self.nginx_domain.domain}{self.location}'
