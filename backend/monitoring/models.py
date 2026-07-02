from django.db import models

class ProbeAudit(models.Model):
    """最近一次采集成功/失败时间（不存历史指标，决策 1）。"""

    TARGET_HOST = 'host'
    TARGET_DATABASE = 'database'
    TARGET_KIND_CHOICES = [
        (TARGET_HOST, '主机'),
        (TARGET_DATABASE, '数据库'),
    ]

    STATUS_OK = 'ok'
    STATUS_ERROR = 'error'
    STATUS_TIMEOUT = 'timeout'
    STATUS_MISCONFIGURED = 'misconfigured'
    STATUS_CHOICES = [
        (STATUS_OK, '成功'),
        (STATUS_ERROR, '错误'),
        (STATUS_TIMEOUT, '超时'),
        (STATUS_MISCONFIGURED, '凭据缺失'),
    ]

    target_kind = models.CharField('目标类型', max_length=16, choices=TARGET_KIND_CHOICES)
    target_id = models.IntegerField('目标 ID（ops.Host.id 或 sqlaudit.DataSource.id）')
    last_status = models.CharField('最近状态', max_length=16, choices=STATUS_CHOICES)
    last_error = models.TextField('最近错误', blank=True, default='')
    last_duration_ms = models.IntegerField('最近耗时 ms', default=0)
    last_collected_at = models.DateTimeField('最近采集时间', auto_now=True)

    class Meta:
        db_table = 'monitoring_probe_audit'
        verbose_name = '采集审计'
        verbose_name_plural = '采集审计'
        unique_together = ('target_kind', 'target_id')
        indexes = [models.Index(fields=['target_kind', 'last_collected_at'])]
