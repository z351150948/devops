"""
Kubernetes 集群管理 API
使用 kubernetes Python 客户端连接并管理 K8s 集群
支持 demo 模式：kubeconfig 为 'demo' 时返回模拟数据
"""
import logging
import tempfile
import os
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response

from .models import K8sCluster
from .serializers import K8sClusterSerializer

logger = logging.getLogger(__name__)


def _is_demo(cluster):
    return cluster.kubeconfig.strip() == 'demo'


# ====== Demo 模拟数据 ======
DEMO_NAMESPACES = [
    {'name': 'default', 'status': 'Active', 'created': '2026-01-15T08:00:00+08:00', 'labels': {}},
    {'name': 'kube-system', 'status': 'Active', 'created': '2026-01-15T08:00:00+08:00', 'labels': {}},
    {'name': 'monitoring', 'status': 'Active', 'created': '2026-02-01T10:30:00+08:00', 'labels': {}},
    {'name': 'production', 'status': 'Active', 'created': '2026-02-10T14:00:00+08:00', 'labels': {'env': 'prod'}},
    {'name': 'staging', 'status': 'Active', 'created': '2026-02-10T14:00:00+08:00', 'labels': {'env': 'staging'}},
]

DEMO_PODS = [
    {'name': 'nginx-deployment-7c5b4f9d8-x2k9p', 'namespace': 'production', 'status': 'Running', 'node': 'node-01', 'ip': '10.244.1.15', 'containers': [{'name': 'nginx', 'image': 'nginx:1.25', 'ready': True}], 'restarts': 0, 'created': '2026-03-05T09:00:00+08:00'},
    {'name': 'nginx-deployment-7c5b4f9d8-m3h7q', 'namespace': 'production', 'status': 'Running', 'node': 'node-02', 'ip': '10.244.2.22', 'containers': [{'name': 'nginx', 'image': 'nginx:1.25', 'ready': True}], 'restarts': 0, 'created': '2026-03-05T09:00:00+08:00'},
    {'name': 'api-server-5f8b7c6d4-r9p2w', 'namespace': 'production', 'status': 'Running', 'node': 'node-01', 'ip': '10.244.1.18', 'containers': [{'name': 'api', 'image': 'myapp/api:v2.1.0', 'ready': True}], 'restarts': 1, 'created': '2026-03-04T11:30:00+08:00'},
    {'name': 'api-server-5f8b7c6d4-t4n8k', 'namespace': 'production', 'status': 'Running', 'node': 'node-03', 'ip': '10.244.3.10', 'containers': [{'name': 'api', 'image': 'myapp/api:v2.1.0', 'ready': True}], 'restarts': 0, 'created': '2026-03-04T11:30:00+08:00'},
    {'name': 'redis-master-0', 'namespace': 'production', 'status': 'Running', 'node': 'node-02', 'ip': '10.244.2.30', 'containers': [{'name': 'redis', 'image': 'redis:7.2-alpine', 'ready': True}], 'restarts': 0, 'created': '2026-02-20T08:00:00+08:00'},
    {'name': 'mysql-primary-0', 'namespace': 'production', 'status': 'Running', 'node': 'node-01', 'ip': '10.244.1.25', 'containers': [{'name': 'mysql', 'image': 'mysql:8.0', 'ready': True}], 'restarts': 0, 'created': '2026-02-18T09:00:00+08:00'},
    {'name': 'web-frontend-6d9f8b7c5-j2m4n', 'namespace': 'staging', 'status': 'Running', 'node': 'node-03', 'ip': '10.244.3.15', 'containers': [{'name': 'frontend', 'image': 'myapp/web:v2.2.0-rc1', 'ready': True}], 'restarts': 0, 'created': '2026-03-08T16:00:00+08:00'},
    {'name': 'web-frontend-6d9f8b7c5-k7p3q', 'namespace': 'staging', 'status': 'Pending', 'node': '', 'ip': '', 'containers': [{'name': 'frontend', 'image': 'myapp/web:v2.2.0-rc1', 'ready': False}], 'restarts': 0, 'created': '2026-03-08T16:05:00+08:00'},
    {'name': 'prometheus-server-0', 'namespace': 'monitoring', 'status': 'Running', 'node': 'node-02', 'ip': '10.244.2.40', 'containers': [{'name': 'prometheus', 'image': 'prom/prometheus:v2.51.0', 'ready': True}], 'restarts': 0, 'created': '2026-02-01T10:30:00+08:00'},
    {'name': 'grafana-7f8c9d6b5-w3x2y', 'namespace': 'monitoring', 'status': 'Running', 'node': 'node-03', 'ip': '10.244.3.35', 'containers': [{'name': 'grafana', 'image': 'grafana/grafana:10.4.0', 'ready': True}], 'restarts': 2, 'created': '2026-02-01T10:35:00+08:00'},
    {'name': 'alertmanager-0', 'namespace': 'monitoring', 'status': 'Running', 'node': 'node-01', 'ip': '10.244.1.42', 'containers': [{'name': 'alertmanager', 'image': 'prom/alertmanager:v0.27.0', 'ready': True}], 'restarts': 0, 'created': '2026-02-01T10:40:00+08:00'},
    {'name': 'coredns-5d78c9689-b8k4m', 'namespace': 'kube-system', 'status': 'Running', 'node': 'node-01', 'ip': '10.244.1.3', 'containers': [{'name': 'coredns', 'image': 'registry.k8s.io/coredns:v1.11.1', 'ready': True}], 'restarts': 0, 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'etcd-master', 'namespace': 'kube-system', 'status': 'Running', 'node': 'master', 'ip': '10.0.0.1', 'containers': [{'name': 'etcd', 'image': 'registry.k8s.io/etcd:3.5.12', 'ready': True}], 'restarts': 0, 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'kube-proxy-n7x2k', 'namespace': 'kube-system', 'status': 'Running', 'node': 'node-01', 'ip': '192.168.1.21', 'containers': [{'name': 'kube-proxy', 'image': 'registry.k8s.io/kube-proxy:v1.29.3', 'ready': True}], 'restarts': 0, 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'debug-pod-manual', 'namespace': 'default', 'status': 'Failed', 'node': 'node-02', 'ip': '10.244.2.99', 'containers': [{'name': 'debug', 'image': 'busybox:latest', 'ready': False}], 'restarts': 5, 'created': '2026-03-07T20:00:00+08:00'},
]

DEMO_SERVICES = [
    {'name': 'nginx-service', 'namespace': 'production', 'type': 'LoadBalancer', 'cluster_ip': '10.96.10.50', 'external_ip': '47.95.15.100', 'ports': '80→30080/TCP, 443→30443/TCP', 'created': '2026-03-05T09:00:00+08:00'},
    {'name': 'api-service', 'namespace': 'production', 'type': 'ClusterIP', 'cluster_ip': '10.96.20.100', 'external_ip': '', 'ports': '8080/TCP', 'created': '2026-03-04T11:30:00+08:00'},
    {'name': 'redis-master', 'namespace': 'production', 'type': 'ClusterIP', 'cluster_ip': '10.96.30.10', 'external_ip': '', 'ports': '6379/TCP', 'created': '2026-02-20T08:00:00+08:00'},
    {'name': 'mysql-primary', 'namespace': 'production', 'type': 'ClusterIP', 'cluster_ip': '10.96.30.20', 'external_ip': '', 'ports': '3306/TCP', 'created': '2026-02-18T09:00:00+08:00'},
    {'name': 'web-frontend', 'namespace': 'staging', 'type': 'NodePort', 'cluster_ip': '10.96.50.10', 'external_ip': '', 'ports': '3000→31000/TCP', 'created': '2026-03-08T16:00:00+08:00'},
    {'name': 'prometheus', 'namespace': 'monitoring', 'type': 'NodePort', 'cluster_ip': '10.96.60.10', 'external_ip': '', 'ports': '9090→30090/TCP', 'created': '2026-02-01T10:30:00+08:00'},
    {'name': 'grafana', 'namespace': 'monitoring', 'type': 'NodePort', 'cluster_ip': '10.96.60.20', 'external_ip': '', 'ports': '3000→30300/TCP', 'created': '2026-02-01T10:35:00+08:00'},
    {'name': 'kubernetes', 'namespace': 'default', 'type': 'ClusterIP', 'cluster_ip': '10.96.0.1', 'external_ip': '', 'ports': '443/TCP', 'created': '2026-01-15T08:00:00+08:00'},
    {'name': 'kube-dns', 'namespace': 'kube-system', 'type': 'ClusterIP', 'cluster_ip': '10.96.0.10', 'external_ip': '', 'ports': '53/UDP, 53/TCP, 9153/TCP', 'created': '2026-01-15T08:00:00+08:00'},
]

DEMO_DEPLOYMENTS = [
    {'name': 'nginx-deployment', 'namespace': 'production', 'replicas': 2, 'ready_replicas': 2, 'available_replicas': 2, 'images': 'nginx:1.25', 'created': '2026-03-05T09:00:00+08:00'},
    {'name': 'api-server', 'namespace': 'production', 'replicas': 2, 'ready_replicas': 2, 'available_replicas': 2, 'images': 'myapp/api:v2.1.0', 'created': '2026-03-04T11:30:00+08:00'},
    {'name': 'web-frontend', 'namespace': 'staging', 'replicas': 2, 'ready_replicas': 1, 'available_replicas': 1, 'images': 'myapp/web:v2.2.0-rc1', 'created': '2026-03-08T16:00:00+08:00'},
    {'name': 'grafana', 'namespace': 'monitoring', 'replicas': 1, 'ready_replicas': 1, 'available_replicas': 1, 'images': 'grafana/grafana:10.4.0', 'created': '2026-02-01T10:35:00+08:00'},
    {'name': 'coredns', 'namespace': 'kube-system', 'replicas': 1, 'ready_replicas': 1, 'available_replicas': 1, 'images': 'registry.k8s.io/coredns:v1.11.1', 'created': '2026-01-15T08:00:00+08:00'},
]


def _get_k8s_client(cluster):
    """根据 kubeconfig 创建 K8s API 客户端"""
    from kubernetes import client, config

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    tmp.write(cluster.kubeconfig)
    tmp.flush()
    tmp.close()

    try:
        config.load_kube_config(config_file=tmp.name)
        return client
    finally:
        os.unlink(tmp.name)


def _filter_by_ns(data, namespace):
    if namespace == '_all':
        return data
    return [d for d in data if d['namespace'] == namespace]


class K8sClusterViewSet(viewsets.ModelViewSet):
    """K8s 集群连接管理"""
    queryset = K8sCluster.objects.all()
    serializer_class = K8sClusterSerializer
    pagination_class = None

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """测试集群连接"""
        cluster = self.get_object()
        if _is_demo(cluster):
            return Response({'success': True, 'message': '连接成功 (Kubernetes v1.29.3) [演示模式]'})
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            version = k8s.VersionApi().get_code()
            cluster.status = 'connected'
            cluster.save(update_fields=['status'])
            return Response({
                'success': True,
                'message': f'连接成功 (Kubernetes {version.git_version})',
            })
        except Exception as e:
            cluster.status = 'error'
            cluster.save(update_fields=['status'])
            return Response({'success': False, 'message': f'连接失败: {str(e)}'})

    @action(detail=True, methods=['get'])
    def namespaces(self, request, pk=None):
        """获取命名空间列表"""
        cluster = self.get_object()
        if _is_demo(cluster):
            return Response(DEMO_NAMESPACES)
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            ns_list = v1.list_namespace()
            data = [{
                'name': ns.metadata.name,
                'status': ns.status.phase,
                'created': ns.metadata.creation_timestamp.isoformat() if ns.metadata.creation_timestamp else '',
                'labels': ns.metadata.labels or {},
            } for ns in ns_list.items]
            return Response(data)
        except Exception as e:
            return Response({'detail': f'获取命名空间失败: {str(e)}'}, status=400)

    @action(detail=True, methods=['get'])
    def pods(self, request, pk=None):
        """获取 Pod 列表"""
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_PODS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            if namespace == '_all':
                pod_list = v1.list_pod_for_all_namespaces()
            else:
                pod_list = v1.list_namespaced_pod(namespace=namespace)

            data = []
            for pod in pod_list.items:
                containers = [{
                    'name': c.name,
                    'image': c.image,
                    'ready': False,
                } for c in (pod.spec.containers or [])]

                if pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        for c in containers:
                            if c['name'] == cs.name:
                                c['ready'] = cs.ready or False
                                c['restart_count'] = cs.restart_count or 0

                data.append({
                    'name': pod.metadata.name,
                    'namespace': pod.metadata.namespace,
                    'status': pod.status.phase,
                    'node': pod.spec.node_name or '',
                    'ip': pod.status.pod_ip or '',
                    'containers': containers,
                    'restarts': sum(c.get('restart_count', 0) for c in containers),
                    'created': pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else '',
                })
            return Response(data)
        except Exception as e:
            return Response({'detail': f'获取 Pod 列表失败: {str(e)}'}, status=400)

    @action(detail=True, methods=['get'])
    def services(self, request, pk=None):
        """获取 Service 列表"""
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_SERVICES, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            if namespace == '_all':
                svc_list = v1.list_service_for_all_namespaces()
            else:
                svc_list = v1.list_namespaced_service(namespace=namespace)

            data = [{
                'name': svc.metadata.name,
                'namespace': svc.metadata.namespace,
                'type': svc.spec.type,
                'cluster_ip': svc.spec.cluster_ip or '',
                'external_ip': ','.join(svc.spec.external_i_ps or []) if svc.spec.external_i_ps else '',
                'ports': ', '.join([
                    f"{p.port}{'→'+str(p.node_port) if p.node_port else ''}/{p.protocol}"
                    for p in (svc.spec.ports or [])
                ]),
                'created': svc.metadata.creation_timestamp.isoformat() if svc.metadata.creation_timestamp else '',
            } for svc in svc_list.items]
            return Response(data)
        except Exception as e:
            return Response({'detail': f'获取 Service 列表失败: {str(e)}'}, status=400)

    @action(detail=True, methods=['get'])
    def deployments(self, request, pk=None):
        """获取 Deployment 列表"""
        cluster = self.get_object()
        namespace = request.query_params.get('namespace', 'default')
        if _is_demo(cluster):
            return Response(_filter_by_ns(DEMO_DEPLOYMENTS, namespace))
        try:
            k8s = _get_k8s_client(cluster)
            apps_v1 = k8s.AppsV1Api()
            if namespace == '_all':
                dep_list = apps_v1.list_deployment_for_all_namespaces()
            else:
                dep_list = apps_v1.list_namespaced_deployment(namespace=namespace)

            data = [{
                'name': dep.metadata.name,
                'namespace': dep.metadata.namespace,
                'replicas': dep.spec.replicas or 0,
                'ready_replicas': dep.status.ready_replicas or 0,
                'available_replicas': dep.status.available_replicas or 0,
                'images': ', '.join([c.image for c in dep.spec.template.spec.containers]),
                'created': dep.metadata.creation_timestamp.isoformat() if dep.metadata.creation_timestamp else '',
            } for dep in dep_list.items]
            return Response(data)
        except Exception as e:
            return Response({'detail': f'获取 Deployment 列表失败: {str(e)}'}, status=400)

    @action(detail=True, methods=['post'], url_path='pods/(?P<pod_name>[^/]+)/restart')
    def restart_pod(self, request, pk=None, pod_name=None):
        """删除 Pod 以触发重启"""
        cluster = self.get_object()
        if _is_demo(cluster):
            return Response({'success': True, 'message': f'Pod {pod_name} 正在重启 [演示模式]'})
        namespace = request.data.get('namespace', 'default')
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
            return Response({'success': True, 'message': f'Pod {pod_name} 正在重启'})
        except Exception as e:
            return Response({'success': False, 'message': f'重启失败: {str(e)}'}, status=400)
