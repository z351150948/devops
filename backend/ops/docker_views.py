"""
Docker 容器管理 API
通过 SSH 连接远程主机执行 Docker 命令
"""
import json
import logging
import paramiko
from rest_framework.decorators import api_view
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def _get_ssh_client(host):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host.ip_address,
        port=host.ssh_port or 22,
        username=host.ssh_user or 'root',
        password=host.ssh_password or None,
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


@api_view(['GET'])
def list_containers(request):
    """获取主机上的 Docker 容器列表"""
    from ops.models import Host
    host_id = request.query_params.get('host_id')
    if not host_id:
        return Response({'detail': '缺少 host_id 参数'}, status=400)

    try:
        host = Host.objects.get(pk=host_id)
    except Host.DoesNotExist:
        return Response({'detail': '主机不存在'}, status=404)

    try:
        client = _get_ssh_client(host)
        code, out, err = _ssh_exec(client, 'docker ps -a --format json 2>/dev/null')
        client.close()

        if code != 0:
            return Response({'detail': f'Docker 命令执行失败: {err}'}, status=400)

        containers = _parse_docker_ps(out)
        return Response(containers)
    except Exception as e:
        return Response({'detail': f'连接失败: {str(e)}'}, status=400)


@api_view(['GET'])
def list_images(request):
    """获取主机上的 Docker 镜像列表"""
    from ops.models import Host
    host_id = request.query_params.get('host_id')
    if not host_id:
        return Response({'detail': '缺少 host_id 参数'}, status=400)

    try:
        host = Host.objects.get(pk=host_id)
    except Host.DoesNotExist:
        return Response({'detail': '主机不存在'}, status=404)

    try:
        client = _get_ssh_client(host)
        code, out, err = _ssh_exec(client, 'docker images --format json 2>/dev/null')
        client.close()

        if code != 0:
            return Response({'detail': f'Docker 命令执行失败: {err}'}, status=400)

        images = _parse_docker_images(out)
        return Response(images)
    except Exception as e:
        return Response({'detail': f'连接失败: {str(e)}'}, status=400)


@api_view(['POST'])
def container_action(request, container_id):
    """容器操作：start / stop / restart"""
    from ops.models import Host
    host_id = request.data.get('host_id')
    action = request.data.get('action')

    if action not in ('start', 'stop', 'restart'):
        return Response({'detail': '无效操作，支持: start / stop / restart'}, status=400)

    try:
        host = Host.objects.get(pk=host_id)
    except Host.DoesNotExist:
        return Response({'detail': '主机不存在'}, status=404)

    try:
        client = _get_ssh_client(host)
        code, out, err = _ssh_exec(client, f'docker {action} {container_id} 2>&1')
        client.close()

        if code == 0:
            return Response({'success': True, 'message': f'容器 {action} 成功'})
        else:
            return Response({'success': False, 'message': f'操作失败: {out}{err}'}, status=400)
    except Exception as e:
        return Response({'detail': f'连接失败: {str(e)}'}, status=400)


@api_view(['DELETE'])
def container_remove(request, container_id):
    """删除容器"""
    from ops.models import Host
    host_id = request.query_params.get('host_id')

    try:
        host = Host.objects.get(pk=host_id)
    except Host.DoesNotExist:
        return Response({'detail': '主机不存在'}, status=404)

    try:
        client = _get_ssh_client(host)
        code, out, err = _ssh_exec(client, f'docker rm -f {container_id} 2>&1')
        client.close()

        if code == 0:
            return Response({'success': True, 'message': '容器已删除'})
        else:
            return Response({'success': False, 'message': f'删除失败: {out}{err}'}, status=400)
    except Exception as e:
        return Response({'detail': f'连接失败: {str(e)}'}, status=400)


@api_view(['GET'])
def container_logs(request, container_id):
    """获取容器日志"""
    from ops.models import Host
    host_id = request.query_params.get('host_id')
    tail = request.query_params.get('tail', '200')

    try:
        host = Host.objects.get(pk=host_id)
    except Host.DoesNotExist:
        return Response({'detail': '主机不存在'}, status=404)

    try:
        client = _get_ssh_client(host)
        code, out, err = _ssh_exec(client, f'docker logs --tail={tail} {container_id} 2>&1', timeout=15)
        client.close()
        return Response({'logs': out})
    except Exception as e:
        return Response({'detail': f'获取日志失败: {str(e)}'}, status=400)


@api_view(['GET'])
def container_inspect(request, container_id):
    """获取容器详情"""
    from ops.models import Host
    host_id = request.query_params.get('host_id')

    try:
        host = Host.objects.get(pk=host_id)
    except Host.DoesNotExist:
        return Response({'detail': '主机不存在'}, status=404)

    try:
        client = _get_ssh_client(host)
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
