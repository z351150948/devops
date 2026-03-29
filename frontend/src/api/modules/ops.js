import request from '../request'

export const getDashboardStats = () => request.get('/dashboard/stats/')

export const getHosts = (params) => request.get('/hosts/', { params })
export const getHost = (id) => request.get(`/hosts/${id}/`)
export const createHost = (data) => request.post('/hosts/', data)
export const updateHost = (id, data) => request.put(`/hosts/${id}/`, data)
export const deleteHost = (id) => request.delete(`/hosts/${id}/`)
export const testHostConnection = (id) => request.post(`/hosts/${id}/test_connection/`)
export const refreshHostInfo = (id) => request.post(`/hosts/${id}/refresh_info/`)

export const getDeployments = (params) => request.get('/deployments/', { params })
export const createDeployment = (data) => request.post('/deployments/', data)
export const updateDeployment = (id, data) => request.put(`/deployments/${id}/`, data)
export const deleteDeployment = (id) => request.delete(`/deployments/${id}/`)
export const approveDeployment = (id, data = {}) => request.post(`/deployments/${id}/approve/`, data)
export const rejectDeployment = (id, data = {}) => request.post(`/deployments/${id}/reject/`, data)
export const rerunDeployment = (id, data = {}) => request.post(`/deployments/${id}/rerun/`, data)
export const rollbackDeployment = (id, data = {}) => request.post(`/deployments/${id}/rollback/`, data)
export const advanceDeploymentBatch = (id, data = {}) => request.post(`/deployments/${id}/advance_batch/`, data)
export const stopDeployment = (id) => request.post(`/deployments/${id}/stop/`)
export const startDeployment = (id) => request.post(`/deployments/${id}/start/`)
export const removeDeployment = (id) => request.post(`/deployments/${id}/remove/`)
export const getDeploymentLogs = (id, tail = 100) => request.get(`/deployments/${id}/logs/`, { params: { tail } })
export const getDeploymentStatus = (id) => request.get(`/deployments/${id}/status_detail/`)
export const getDeploymentApprovalFlows = (params) => request.get('/deployment-approval-flows/', { params })
export const createDeploymentApprovalFlow = (data) => request.post('/deployment-approval-flows/', data)
export const updateDeploymentApprovalFlow = (id, data) => request.put(`/deployment-approval-flows/${id}/`, data)
export const deleteDeploymentApprovalFlow = (id) => request.delete(`/deployment-approval-flows/${id}/`)

export const getAlerts = (params) => request.get('/alerts/', { params })
export const updateAlert = (id, data) => request.patch(`/alerts/${id}/`, data)
export const deleteAlert = (id) => request.delete(`/alerts/${id}/`)

export const getLogs = (params) => request.get('/logs/', { params })

export const getUsers = (params) => request.get('/users/', { params })

export const getLokiLabels = (params) => request.get('/loki/labels/', { params })
export const getLokiLabelValues = (name, params) => request.get(`/loki/label/${name}/values/`, { params })
export const queryLokiLogs = (params) => request.get('/loki/query_range/', { params })
export const getLokiSeries = (params) => request.get('/loki/series/', { params })

export const getLogProviders = () => request.get('/log/providers/')
export const getLogProviderCatalog = (provider, data) => request.post(`/log/providers/${provider}/catalog/`, data)
export const queryLogs = (data) => request.post('/log/query/', data)

export const getLogDataSources = (params) => request.get('/log/datasources/', { params })
export const createLogDataSource = (data) => request.post('/log/datasources/', data)
export const updateLogDataSource = (id, data) => request.put(`/log/datasources/${id}/`, data)
export const deleteLogDataSource = (id) => request.delete(`/log/datasources/${id}/`)
export const testLogDataSource = (id) => request.post(`/log/datasources/${id}/test_connection/`)

export const getObservabilityOverview = (params) => request.get('/observability/overview/', { params })
export const getTracingCatalog = (params) => request.get('/observability/tracing/catalog/', { params })
export const searchTracing = (data) => request.post('/observability/tracing/search/', data)
export const getTraceDetail = (traceId, params) => request.get(`/observability/tracing/traces/${traceId}/`, { params })
