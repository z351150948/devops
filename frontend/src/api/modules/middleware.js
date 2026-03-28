import request from '@/api/request'

export const getMiddlewareOverview = () => request.get('/middleware/overview/')

export const runMiddlewareAction = (module, targetId, action, payload = {}) =>
  request.post('/middleware/action/', {
    module,
    target_id: targetId,
    action,
    payload,
  })
