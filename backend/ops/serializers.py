from rest_framework import serializers
from .models import (
    Host, Deployment, Alert, LogEntry, LogDataSource, K8sCluster, DockerHost,
    NginxEnvironment, NginxCertificate, NginxDomain, NginxRoute,
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


class DeploymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    environment_display = serializers.CharField(source='get_environment_display', read_only=True)
    host_name = serializers.CharField(source='host.hostname', read_only=True, default='')

    class Meta:
        model = Deployment
        fields = '__all__'


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
            'kubeconfig': {'write_only': True},  # 安全: kubeconfig 不在列表中返回
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
        return [{'id': e.id, 'name': e.name} for e in obj.environments.all()]

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



