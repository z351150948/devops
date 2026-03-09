"""
Kubernetes 集群管理 API
使用 kubernetes Python 客户端连接并管理 K8s 集群
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


def _get_k8s_client(cluster):
    """根据 kubeconfig 创建 K8s API 客户端"""
    from kubernetes import client, config

    # 将 kubeconfig 写入临时文件
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    tmp.write(cluster.kubeconfig)
    tmp.flush()
    tmp.close()

    try:
        config.load_kube_config(config_file=tmp.name)
        return client
    finally:
        os.unlink(tmp.name)


class K8sClusterViewSet(viewsets.ModelViewSet):
    """K8s 集群连接管理"""
    queryset = K8sCluster.objects.all()
    serializer_class = K8sClusterSerializer
    pagination_class = None

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """测试集群连接"""
        cluster = self.get_object()
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

                # 填充 ready 状态
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
        namespace = request.data.get('namespace', 'default')
        try:
            k8s = _get_k8s_client(cluster)
            v1 = k8s.CoreV1Api()
            v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
            return Response({'success': True, 'message': f'Pod {pod_name} 正在重启'})
        except Exception as e:
            return Response({'success': False, 'message': f'重启失败: {str(e)}'}, status=400)
