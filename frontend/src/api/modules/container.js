import request from '@/api/request'

// ====== Docker 容器 ======
export const getDockerContainers = (hostId) => request.get('/docker/containers/', { params: { host_id: hostId } })
export const getDockerImages = (hostId) => request.get('/docker/images/', { params: { host_id: hostId } })
export const dockerContainerAction = (containerId, hostId, action) =>
  request.post(`/docker/containers/${containerId}/action/`, { host_id: hostId, action })
export const dockerContainerRemove = (containerId, hostId) =>
  request.delete(`/docker/containers/${containerId}/remove/`, { params: { host_id: hostId } })
export const getDockerContainerLogs = (containerId, hostId, tail = 200) =>
  request.get(`/docker/containers/${containerId}/logs/`, { params: { host_id: hostId, tail } })
export const getDockerContainerInspect = (containerId, hostId) =>
  request.get(`/docker/containers/${containerId}/inspect/`, { params: { host_id: hostId } })

// ====== K8s 集群 ======
export const getK8sClusters = () => request.get('/k8s/clusters/')
export const createK8sCluster = (data) => request.post('/k8s/clusters/', data)
export const updateK8sCluster = (id, data) => request.put(`/k8s/clusters/${id}/`, data)
export const deleteK8sCluster = (id) => request.delete(`/k8s/clusters/${id}/`)
export const testK8sConnection = (id) => request.post(`/k8s/clusters/${id}/test_connection/`)
export const getK8sNamespaces = (id) => request.get(`/k8s/clusters/${id}/namespaces/`)
export const getK8sPods = (id, ns = 'default') => request.get(`/k8s/clusters/${id}/pods/`, { params: { namespace: ns } })
export const getK8sServices = (id, ns = 'default') => request.get(`/k8s/clusters/${id}/services/`, { params: { namespace: ns } })
export const getK8sDeployments = (id, ns = 'default') => request.get(`/k8s/clusters/${id}/deployments/`, { params: { namespace: ns } })
export const restartK8sPod = (clusterId, podName, ns) => request.post(`/k8s/clusters/${clusterId}/pods/${podName}/restart/`, { namespace: ns })
