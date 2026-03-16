import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { getCurrentUser, login as loginApi, logout as logoutApi } from '@/api/modules/rbac'

const TOKEN_KEY = 'agdevops_token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const currentUser = ref(null)
  const initialized = ref(false)

  const isAuthenticated = computed(() => !!token.value && !!currentUser.value)
  const permissions = computed(() => currentUser.value?.effective_permissions || [])
  const displayName = computed(() => {
    if (!currentUser.value) return ''
    return currentUser.value.display_name || currentUser.value.username || ''
  })

  function persistToken(value) {
    token.value = value || ''
    if (token.value) {
      localStorage.setItem(TOKEN_KEY, token.value)
    } else {
      localStorage.removeItem(TOKEN_KEY)
    }
  }

  function setUser(user) {
    currentUser.value = user || null
  }

  function clearSession() {
    persistToken('')
    setUser(null)
  }

  async function bootstrap() {
    if (initialized.value) return currentUser.value
    return reloadProfile()
  }

  async function reloadProfile() {
    initialized.value = true
    if (!token.value) return null
    try {
      const user = await getCurrentUser()
      setUser(user)
      return user
    } catch (error) {
      clearSession()
      return null
    }
  }

  async function login(payload) {
    const response = await loginApi(payload)
    persistToken(response.token)
    setUser(response.user)
    initialized.value = true
    return response.user
  }

  async function logout() {
    try {
      if (token.value) {
        await logoutApi()
      }
    } finally {
      clearSession()
      initialized.value = true
    }
  }

  function hasPermission(code) {
    if (!code) return true
    if (currentUser.value?.is_superuser) return true
    return permissions.value.includes(code)
  }

  function hasAnyPermission(codes = []) {
    if (!codes.length) return true
    return codes.some(code => hasPermission(code))
  }

  function hasAllPermissions(codes = []) {
    if (!codes.length) return true
    return codes.every(code => hasPermission(code))
  }

  return {
    token,
    currentUser,
    initialized,
    isAuthenticated,
    permissions,
    displayName,
    bootstrap,
    login,
    logout,
    clearSession,
    hasPermission,
    hasAnyPermission,
    hasAllPermissions,
    reloadProfile,
  }
})
