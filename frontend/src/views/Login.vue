<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-brand">
        <div class="brand-mark">Ag</div>
        <div>
          <div class="brand-title">AgDevOps</div>
          <div class="brand-subtitle">统一运维平台登录</div>
        </div>
      </div>

      <el-form :model="form" @submit.prevent="handleLogin">
        <el-form-item>
          <el-input v-model="form.username" size="large" placeholder="用户名" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" size="large" type="password" show-password placeholder="密码" />
        </el-form-item>
        <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="handleLogin">
          登录平台
        </el-button>
      </el-form>

      <div class="auth-tip">
        默认本地管理员：`admin` / `Admin@123456`
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const loading = ref(false)
const form = reactive({
  username: 'admin',
  password: 'Admin@123456',
})

async function handleLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }

  loading.value = true
  try {
    await authStore.login(form)
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || '/dashboard')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(34, 197, 94, 0.16), transparent 32%),
    radial-gradient(circle at bottom right, rgba(59, 130, 246, 0.18), transparent 38%),
    linear-gradient(135deg, #08111f 0%, #101c2f 54%, #17263b 100%);
}

.auth-card {
  width: min(420px, 100%);
  padding: 32px;
  border-radius: 24px;
  background: rgba(10, 18, 31, 0.82);
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.45);
}

.auth-brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 28px;
}

.brand-mark {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  display: grid;
  place-items: center;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #22c55e, #0ea5e9);
}

.brand-title {
  font-size: 24px;
  font-weight: 700;
  color: #f8fafc;
}

.brand-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 13px;
}

.submit-btn {
  width: 100%;
}

.auth-tip {
  margin-top: 16px;
  color: #94a3b8;
  font-size: 12px;
}
</style>
