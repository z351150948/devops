"""监控 API 的 DRF Serializer。"""
from rest_framework import serializers


class HostProbeRequestSerializer(serializers.Serializer):
    """批量 host probe 请求体。空 ids = 全表。"""
    ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)


class HostProbeResultSerializer(serializers.Serializer):
    """单 host probe 结果（响应中单条 results[] 项）。"""
    id = serializers.IntegerField()
    hostname = serializers.CharField()
    ip = serializers.CharField()
    status = serializers.CharField()
    duration_ms = serializers.IntegerField()
    metrics = serializers.JSONField(allow_null=True)
    error = serializers.CharField(allow_null=True)


class DatabaseProbeResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    type = serializers.CharField()
    host = serializers.CharField(allow_null=True)
    port = serializers.IntegerField(allow_null=True)
    status = serializers.CharField()
    duration_ms = serializers.IntegerField()
    metrics = serializers.JSONField(allow_null=True)
    error = serializers.CharField(allow_null=True)


class ProbeSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    ok = serializers.IntegerField()
    error = serializers.IntegerField()
    timeout = serializers.IntegerField()
    duration_ms = serializers.IntegerField()
