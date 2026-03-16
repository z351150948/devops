"""
Docker 环境管理 API
- DockerHostViewSet: Docker 主机 CRUD + 测试连接
- 容器/镜像管理: 通过 SSH 连接远程主机执行 Docker 命令
"""
import json
import logging
import paramiko
from rest_framework import viewsets
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import DockerHost
from .serializers import DockerHostSerializer
from rbac.permissions import RBACPermissionMixin, build_rbac_permission

logger = logging.getLogger(__name__)


# ====== SSH 工具函数 ======

def _get_ssh_client_from_docker_host(docker_host):
    """使用 DockerHost 模型创建 SSH 连接"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=docker_host.ip_address,
        port=docker_host.ssh_port or 22,
        username=docker_host.ssh_user or 'root',
        password=docker_host.ssh_password or None,
        timeout=15,
    )
    return client


def _ssh_exec(client, cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    return exit_code, out, err


def _parse_docker_ps(raw_output):
    """解析 docker ps --format json 输出"""
    containers = []
    for line in raw_output.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            c = json.loads(line)
            containers.append({
                'id': c.get('ID', ''),
                'name': c.get('Names', ''),
                'image': c.get('Image', ''),
                'status': c.get('Status', ''),
                'state': c.get('State', ''),
                'ports': c.get('Ports', ''),
                'created': c.get('CreatedAt', c.get('RunningFor', '')),
                'size': c.get('Size', ''),
            })
        except json.JSONDecodeError:
            continue
    return containers


def _parse_docker_images(raw_output):
    """解析 docker images --format json 输出"""
    images = []
    for line in raw_output.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            img = json.loads(line)
            images.append({
                'id': img.get('ID', ''),
                'repository': img.get('Repository', ''),
                'tag': img.get('Tag', ''),
                'size': img.get('Size', ''),
                'created': img.get('CreatedAt', img.get('CreatedSince', '')),
            })
        except json.JSONDecodeError:
            continue
    return images


def _get_docker_host(host_id):
    """获取 DockerHost 实例"""
    try:
        return DockerHost.objects.get(pk=host_id)
    except DockerHost.DoesNotExist:
        return None


# ====== DockerHost ViewSet ======

class DockerHostViewSet(RBACPermissionMixin, viewsets.ModelViewSet):
    queryset = DockerHost.objects.all()
    serializer_class = DockerHostSerializer
    rbac_permissions = {
        'list': ['ops.docker.view'],
        'retrieve': ['ops.docker.view'],
        'create': ['ops.docker.manage'],
        'update': ['ops.docker.manage'],
        'partial_update': ['ops.docker.manage'],
        'destroy': ['ops.docker.manage'],
        'test_connection': ['ops.docker.manage'],
    }

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """测试 Docker 主机连接"""
        docker_host = self.get_object()
        try:
            client = _get_ssh_client_from_docker_host(docker_host)
            code, out, err = _ssh_exec(client, 'docker version --format "{{.Server.Version}}" 2>/dev/null')
            client.close()

            if code == 0 and out.strip():
                docker_host.status = 'connected'
                docker_host.docker_api_version = out.strip()
                docker_host.save()
                return Response({
                    'success': True,
                    'message': f'连接成功，Docker 版本: {out.strip()}'
                })
            else:
                docker_host.status = 'error'
                docker_host.save()
                return Response({
                    'success': False,
                    'message': f'Docker 未安装或无法执行: {err}'
                })
        except Exception as e:
            docker_host.status = 'error'
            docker_host.save()
            return Response({
                'success': False,
                'message': f'SSH 连接失败: {str(e)}'
            })


# ====== 容器/镜像管理（使用 DockerHost） ======

@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.docker.view')])
def list_containers(request):
    """获取主机上的 Docker 容器列表"""
    host_id = request.query_params.get('host_id')
    if not host_id:
        return Response({'detail': '缺少 host_id 参数'}, status=400)

    docker_host = _get_docker_host(host_id)
    if not docker_host:
        return Response({'detail': 'Docker 环境不存在'}, status=404)

    try:
        client = _get_ssh_client_from_docker_host(docker_host)
        code, out, err = _ssh_exec(client, 'docker ps -a --format json 2>/dev/null')
        client.close()

        if code != 0:
            return Response({'detail': f'Docker 命令执行失败: {err}'}, status=400)

        containers = _parse_docker_ps(out)
        return Response(containers)
    except Exception as e:
        return Response({'detail': f'连接失败: {str(e)}'}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.docker.view')])
def list_images(request):
    """获取主机上的 Docker 镜像列表"""
    host_id = request.query_params.get('host_id')
    if not host_id:
        return Response({'detail': '缺少 host_id 参数'}, status=400)

    docker_host = _get_docker_host(host_id)
    if not docker_host:
        return Response({'detail': 'Docker 环境不存在'}, status=404)

    try:
        client = _get_ssh_client_from_docker_host(docker_host)
        code, out, err = _ssh_exec(client, 'docker images --format json 2>/dev/null')
        client.close()

        if code != 0:
            return Response({'detail': f'Docker 命令执行失败: {err}'}, status=400)

        images = _parse_docker_images(out)
        return Response(images)
    except Exception as e:
        return Response({'detail': f'连接失败: {str(e)}'}, status=400)


@api_view(['POST'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.docker.manage')])
def container_action(request, container_id):
    """容器操作：start / stop / restart"""
    host_id = request.data.get('host_id')
    action_name = request.data.get('action')

    if action_name not in ('start', 'stop', 'restart'):
        return Response({'detail': '无效操作，支持: start / stop / restart'}, status=400)

    docker_host = _get_docker_host(host_id)
    if not docker_host:
        return Response({'detail': 'Docker 环境不存在'}, status=404)

    try:
        client = _get_ssh_client_from_docker_host(docker_host)
        code, out, err = _ssh_exec(client, f'docker {action_name} {container_id} 2>&1')
        client.close()

        if code == 0:
            return Response({'success': True, 'message': f'容器 {action_name} 成功'})
        else:
            return Response({'success': False, 'message': f'操作失败: {out}{err}'}, status=400)
    except Exception as e:
        return Response({'detail': f'连接失败: {str(e)}'}, status=400)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.docker.manage')])
def container_remove(request, container_id):
    """删除容器"""
    host_id = request.query_params.get('host_id')

    docker_host = _get_docker_host(host_id)
    if not docker_host:
        return Response({'detail': 'Docker 环境不存在'}, status=404)

    try:
        client = _get_ssh_client_from_docker_host(docker_host)
        code, out, err = _ssh_exec(client, f'docker rm -f {container_id} 2>&1')
        client.close()

        if code == 0:
            return Response({'success': True, 'message': '容器已删除'})
        else:
            return Response({'success': False, 'message': f'删除失败: {out}{err}'}, status=400)
    except Exception as e:
        return Response({'detail': f'连接失败: {str(e)}'}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.docker.view')])
def container_logs(request, container_id):
    """获取容器日志"""
    host_id = request.query_params.get('host_id')
    tail = request.query_params.get('tail', '200')

    docker_host = _get_docker_host(host_id)
    if not docker_host:
        return Response({'detail': 'Docker 环境不存在'}, status=404)

    try:
        client = _get_ssh_client_from_docker_host(docker_host)
        code, out, err = _ssh_exec(client, f'docker logs --tail={tail} {container_id} 2>&1', timeout=15)
        client.close()
        return Response({'logs': out})
    except Exception as e:
        return Response({'detail': f'获取日志失败: {str(e)}'}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated, build_rbac_permission('ops.docker.view')])
def container_inspect(request, container_id):
    """获取容器详情"""
    host_id = request.query_params.get('host_id')

    docker_host = _get_docker_host(host_id)
    if not docker_host:
        return Response({'detail': 'Docker 环境不存在'}, status=404)

    try:
        client = _get_ssh_client_from_docker_host(docker_host)
        code, out, err = _ssh_exec(client, f'docker inspect {container_id} 2>&1')
        client.close()

        if code == 0:
            try:
                data = json.loads(out)
                return Response(data[0] if data else {})
            except json.JSONDecodeError:
                return Response({'raw': out})
        else:
            return Response({'detail': f'Inspect 失败: {out}{err}'}, status=400)
    except Exception as e:
        return Response({'detail': f'连接失败: {str(e)}'}, status=400)
