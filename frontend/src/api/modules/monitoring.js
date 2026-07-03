import request from '../request'

export const probeHosts = (payload = {}) => request.post('/monitoring/hosts/probe/', payload)
export const probeHost = (id) => request.get(`/monitoring/hosts/${id}/probe/`)
export const probeDatabases = (payload = {}) => request.post('/monitoring/databases/probe/', payload)
export const probeDatabase = (id) => request.get(`/monitoring/databases/${id}/probe/`)