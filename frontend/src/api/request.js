import axios from 'axios'
import { ElMessage } from 'element-plus'

const TOKEN_KEY = 'agdevops_token'

const request = axios.create({
    baseURL: '/api',
    timeout: 15000,
})

request.interceptors.request.use((config) => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (token) {
        config.headers = config.headers || {}
        config.headers.Authorization = `Token ${token}`
    }
    return config
})

// 响应拦截器
request.interceptors.response.use(
    (response) => response.data,
    (error) => {
        const msg = error.response?.data?.detail || error.message || '请求失败'
        if (error.response?.status === 401) {
            localStorage.removeItem(TOKEN_KEY)
            if (!window.location.pathname.startsWith('/login')) {
                const redirect = encodeURIComponent(window.location.pathname + window.location.search)
                window.location.href = `/login?redirect=${redirect}`
            }
        }
        ElMessage.error(msg)
        return Promise.reject(error)
    }
)

export default request
