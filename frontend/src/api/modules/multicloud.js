import request from '../request'

export const getMultiCloudCatalog = () => request.get('/multicloud/catalog/')
export const getMultiCloudOverview = () => request.get('/multicloud/overview/')
export const getMultiCloudTopology = (params) => request.get('/multicloud/topology/', { params })
export const getMultiCloudCostTrend = (params) => request.get('/multicloud/cost-trend/', { params })
export const runMultiCloudBatchSync = (data) => request.post('/multicloud/batch-sync/', data)
export const runMultiCloudBatchAction = (data) => request.post('/multicloud/batch-actions/', data)

export const getCloudCredentials = (params) => request.get('/multicloud/credentials/', { params })
export const createCloudCredential = (data) => request.post('/multicloud/credentials/', data)
export const updateCloudCredential = (id, data) => request.put(`/multicloud/credentials/${id}/`, data)
export const deleteCloudCredential = (id) => request.delete(`/multicloud/credentials/${id}/`)
export const testCloudCredential = (id) => request.post(`/multicloud/credentials/${id}/test_connection/`)
export const syncCloudCredential = (id) => request.post(`/multicloud/credentials/${id}/sync_all/`)

export const getCloudEnvironments = (params) => request.get('/multicloud/environments/', { params })
export const createCloudEnvironment = (data) => request.post('/multicloud/environments/', data)
export const updateCloudEnvironment = (id, data) => request.put(`/multicloud/environments/${id}/`, data)
export const deleteCloudEnvironment = (id) => request.delete(`/multicloud/environments/${id}/`)
export const syncCloudEnvironment = (id) => request.post(`/multicloud/environments/${id}/sync/`)
export const syncCloudEnvironmentCmdb = (id) => request.post(`/multicloud/environments/${id}/sync_cmdb/`)

export const getCloudAssets = (params) => request.get('/multicloud/assets/', { params })
export const getCloudSyncTasks = (params) => request.get('/multicloud/sync-tasks/', { params })
