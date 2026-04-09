<template>
  <div class="transaction-ticket-page fade-in">
    <section class="hero panel">
      <div class="release-hero-title-row release-hero-title-inline">
        <span class="ticket-header-icon"><el-icon><Tickets /></el-icon></span>
        <h2>事务工单</h2>
        <p class="ticket-hero-desc">覆盖变更执行、巡检维护、权限开通与故障处置，统一走审批流并沉淀处理窗口。</p>
      </div>
      <div class="hero-actions">
        <el-button v-if="canCreate" type="primary" @click="openCreateDialog">
          <el-icon><Plus /></el-icon>
          新建事务工单
        </el-button>
      </div>
    </section>

    <div class="stats-grid release-stats">
      <div class="stat-card release-stat-card">
        <div class="stat-value">{{ summary.total }}</div>
        <div class="stat-label">工单总数</div>
      </div>
      <div class="stat-card release-stat-card warning-card">
        <div class="stat-value">{{ summary.pending }}</div>
        <div class="stat-label">待审批</div>
      </div>
      <div class="stat-card release-stat-card success-card">
        <div class="stat-value">{{ summary.processing }}</div>
        <div class="stat-label">处理中</div>
      </div>
      <div class="stat-card release-stat-card danger-card">
        <div class="stat-value">{{ summary.urgent }}</div>
        <div class="stat-label">高优先级</div>
      </div>
    </div>

    <div v-if="platformTips.length" class="ticket-alert-strip">
      <span class="ticket-alert-strip__label">平台提醒</span>
      <el-tag
        v-for="item in platformTips"
        :key="item"
        size="small"
        effect="light"
        type="info"
        class="ticket-alert-strip__tag"
      >
        {{ item }}
      </el-tag>
    </div>

    <div class="table-card">
      <div class="filter-bar ticket-filter-bar">
        <el-select v-model="typeFilter" clearable placeholder="工单类型" style="width: 128px">
          <el-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="statusFilter" clearable placeholder="状态" style="width: 118px">
          <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="priorityFilter" clearable placeholder="优先级" style="width: 118px">
          <el-option v-for="item in priorityOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="bizFilter" clearable filterable placeholder="业务线" style="width: 128px" @change="handleBizFilterChange">
          <el-option v-for="item in businessLineOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="envFilter" clearable placeholder="环境" style="width: 118px">
          <el-option v-for="item in envFilterOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-input v-model="search" clearable placeholder="搜索标题 / 申请人 / 处理人" style="width: 280px" />
        <el-button class="filter-refresh-btn" :loading="loading" @click="loadTickets">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
      </div>

      <el-table v-loading="loading" :data="filteredTickets" stripe style="width: 100%">
        <el-table-column label="工单标题" min-width="240">
          <template #default="{ row }">
            <div class="stack-cell">
              <span class="ticket-title">{{ row.title }}</span>
              <div class="sub-text">{{ row.description || '暂无补充说明' }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="light" :type="typeTagType(row.ticket_type)">{{ typeLabel(row.ticket_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="业务线 / 环境" min-width="160">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.business_line || '-' }}</span>
              <div class="sub-text">{{ row.environment_display || environmentLabel(row.environment) }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="审批流" min-width="180">
          <template #default="{ row }">
            <div class="stack-cell">
              <span>{{ row.approval_flow_name || '默认审批' }}</span>
              <div class="sub-text">{{ row.window || '按需执行' }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="priorityTagType(row.priority)">{{ priorityLabel(row.priority) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="applicant" label="申请人" width="120" />
        <el-table-column prop="owner" label="处理人" width="120" />
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'pending' && canApprove"
              link
              type="success"
              size="small"
              @click="approveTicket(row)"
            >
              通过
            </el-button>
            <el-button
              v-if="row.status === 'pending' && canApprove"
              link
              type="danger"
              size="small"
              @click="rejectTicket(row)"
            >
              驳回
            </el-button>
            <el-button
              v-if="row.status === 'approved' && canManage"
              link
              type="primary"
              size="small"
              @click="startTicket(row)"
            >
              开始处理
            </el-button>
            <el-button
              v-if="row.status === 'processing' && canManage"
              link
              type="success"
              size="small"
              @click="completeTicket(row)"
            >
              完成
            </el-button>
            <el-button link type="info" size="small" @click="viewTicket(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="createVisible" title="新建事务工单" width="760px" append-to-body destroy-on-close>
      <el-form :model="ticketForm" label-width="96px" class="ticket-form-grid">
        <el-form-item label="工单标题" class="span-2" required><el-input v-model="ticketForm.title" /></el-form-item>
        <el-form-item label="事务类型" required>
          <el-select v-model="ticketForm.ticket_type" style="width: 100%">
            <el-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级" required>
          <el-select v-model="ticketForm.priority" style="width: 100%">
            <el-option v-for="item in priorityOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="业务线" required>
          <el-select v-model="ticketForm.business_line" filterable style="width: 100%" @change="handleBusinessLineChange">
            <el-option v-for="item in businessLineOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="环境" required>
          <el-select v-model="ticketForm.environment" style="width: 100%">
            <el-option v-for="item in formEnvironmentOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="处理人"><el-input v-model="ticketForm.owner" placeholder="如：值班运维 / 平台组" /></el-form-item>
        <el-form-item label="执行窗口"><el-input v-model="ticketForm.window" placeholder="如：今晚 22:00-23:00" /></el-form-item>
        <el-form-item label="审批流" class="span-2">
          <el-select v-model="ticketForm.approval_flow" clearable filterable style="width: 100%" placeholder="选择审批流">
            <el-option
              v-for="item in transactionFlows"
              :key="item.id"
              :label="`${item.name} · ${item.environment_display || '全部环境'}`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="说明" class="span-2"><el-input v-model="ticketForm.description" type="textarea" :rows="4" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="createTicket">提交工单</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="事务工单详情" width="760px" append-to-body destroy-on-close>
      <el-descriptions v-if="activeTicket" :column="2" border size="small">
        <el-descriptions-item label="工单标题" :span="2">{{ activeTicket.title }}</el-descriptions-item>
        <el-descriptions-item label="事务类型">{{ typeLabel(activeTicket.ticket_type) }}</el-descriptions-item>
        <el-descriptions-item label="优先级">{{ priorityLabel(activeTicket.priority) }}</el-descriptions-item>
        <el-descriptions-item label="业务线">{{ activeTicket.business_line || '-' }}</el-descriptions-item>
        <el-descriptions-item label="环境">{{ activeTicket.environment_display || environmentLabel(activeTicket.environment) }}</el-descriptions-item>
        <el-descriptions-item label="审批流">{{ activeTicket.approval_flow_name || '默认审批' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusLabel(activeTicket.status) }}</el-descriptions-item>
        <el-descriptions-item label="申请人">{{ activeTicket.applicant || '-' }}</el-descriptions-item>
        <el-descriptions-item label="处理人">{{ activeTicket.owner || '-' }}</el-descriptions-item>
        <el-descriptions-item label="执行窗口">{{ activeTicket.window || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatTime(activeTicket.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatTime(activeTicket.updated_at) }}</el-descriptions-item>
        <el-descriptions-item label="说明" :span="2">{{ activeTicket.description || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, RefreshRight, Tickets } from '@element-plus/icons-vue'
import { getResourceNodeTree } from '@/api/modules/cmdb'
import {
  approveTransactionTicket,
  completeTransactionTicket,
  createTransactionTicket,
  getDeploymentApprovalFlows,
  getTransactionTickets,
  rejectTransactionTicket,
  startProcessTransactionTicket,
} from '@/api/modules/ops'
import { useAuthStore } from '@/stores/auth'
import { enrichWorkOrderFlows } from '@/utils/workorderFlows'

const authStore = useAuthStore()

const tickets = ref([])
const flows = ref([])
const resourceTree = ref([])
const loading = ref(false)
const submitting = ref(false)
const createVisible = ref(false)
const detailVisible = ref(false)
const activeTicket = ref(null)

const search = ref('')
const typeFilter = ref('')
const statusFilter = ref('')
const priorityFilter = ref('')
const bizFilter = ref('')
const envFilter = ref('')

const typeOptions = [
  { label: '变更执行', value: 'change' },
  { label: '巡检任务', value: 'inspection' },
  { label: '权限开通', value: 'access' },
  { label: '故障处理', value: 'incident' },
]
const priorityOptions = [
  { label: '高', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '低', value: 'low' },
]
const statusOptions = [
  { label: '待审批', value: 'pending' },
  { label: '已通过', value: 'approved' },
  { label: '处理中', value: 'processing' },
  { label: '已完成', value: 'done' },
  { label: '已驳回', value: 'rejected' },
]

const ticketForm = ref({})

const canCreate = computed(() => authStore.hasPermission('ops.ticket.manage'))
const canManage = computed(() => authStore.hasPermission('ops.ticket.manage'))
const canApprove = computed(() => authStore.hasPermission('ops.ticket.approve'))

const businessLineOptions = computed(() => (resourceTree.value || [])
  .filter(item => item.node_type === 'biz')
  .map(item => ({ label: item.name, value: item.name })))

const envFilterOptions = computed(() => {
  if (!bizFilter.value) return listEnvironments(resourceTree.value)
  const bizNode = (resourceTree.value || []).find(item => item.node_type === 'biz' && item.name === bizFilter.value)
  return (bizNode?.children || []).map(item => ({ label: environmentLabel(item.name), value: item.name }))
})

const formEnvironmentOptions = computed(() => {
  if (!ticketForm.value.business_line) return []
  const bizNode = (resourceTree.value || []).find(item => item.node_type === 'biz' && item.name === ticketForm.value.business_line)
  return (bizNode?.children || []).map(item => ({ label: environmentLabel(item.name), value: item.name }))
})

const transactionFlows = computed(() => {
  const matched = flows.value.filter(item => (item.ticket_types || []).includes('transaction'))
  return matched.length ? matched : flows.value.filter(item => item.is_active)
})

const filteredTickets = computed(() => tickets.value.filter((item) => {
  if (typeFilter.value && item.ticket_type !== typeFilter.value) return false
  if (statusFilter.value && item.status !== statusFilter.value) return false
  if (priorityFilter.value && item.priority !== priorityFilter.value) return false
  if (bizFilter.value && item.business_line !== bizFilter.value) return false
  if (envFilter.value && item.environment !== envFilter.value) return false
  const keyword = search.value.trim().toLowerCase()
  if (!keyword) return true
  return [item.title, item.applicant, item.owner, item.description].some(value => String(value || '').toLowerCase().includes(keyword))
}))

const summary = computed(() => ({
  total: tickets.value.length,
  pending: tickets.value.filter(item => item.status === 'pending').length,
  processing: tickets.value.filter(item => item.status === 'processing').length,
  urgent: tickets.value.filter(item => item.priority === 'high').length,
}))

const platformTips = computed(() => {
  const tips = []
  if (summary.value.pending) tips.push(`当前有 ${summary.value.pending} 张事务工单待审批`)
  if (summary.value.processing) tips.push(`当前有 ${summary.value.processing} 张事务工单处理中`)
  if (!transactionFlows.value.length) tips.push('当前未配置事务工单专属审批流，将回退展示通用审批流')
  return tips.slice(0, 3)
})

function resetTicketForm() {
  ticketForm.value = {
    title: '',
    ticket_type: 'change',
    priority: 'medium',
    business_line: '',
    environment: '',
    approval_flow: null,
    owner: '',
    window: '',
    description: '',
  }
}

async function loadTickets() {
  loading.value = true
  try {
    const response = await getTransactionTickets()
    tickets.value = Array.isArray(response?.results) ? response.results : (response || [])
  } catch (error) {
    tickets.value = []
    ElMessage.error(resolveErrorMessage(error, '事务工单加载失败'))
  } finally {
    loading.value = false
  }
}

async function loadFlows() {
  try {
    const response = await getDeploymentApprovalFlows()
    const list = enrichWorkOrderFlows(response?.results || response || [])
    flows.value = list.length ? list : []
  } catch {
    flows.value = []
  }
}

async function loadResourceTree() {
  try {
    const response = await getResourceNodeTree()
    resourceTree.value = response?.results || response || []
  } catch {
    resourceTree.value = []
  }
}

function listEnvironments(tree) {
  const map = new Map()
  ;(tree || []).forEach((bizNode) => {
    ;(bizNode.children || []).forEach((envNode) => {
      if (!map.has(envNode.name)) {
        map.set(envNode.name, { label: environmentLabel(envNode.name), value: envNode.name })
      }
    })
  })
  return Array.from(map.values())
}

function environmentLabel(value) {
  return ({ prod: '生产', test: '测试', dev: '开发' }[value] || value || '-')
}

function typeLabel(value) {
  return typeOptions.find(item => item.value === value)?.label || value
}

function priorityLabel(value) {
  return priorityOptions.find(item => item.value === value)?.label || value
}

function statusLabel(value) {
  return statusOptions.find(item => item.value === value)?.label || value
}

function typeTagType(value) {
  return ({ change: 'warning', inspection: 'info', access: 'success', incident: 'danger' }[value] || 'info')
}

function priorityTagType(value) {
  return ({ high: 'danger', medium: 'warning', low: 'info' }[value] || 'info')
}

function statusTagType(value) {
  return ({ pending: 'warning', approved: 'success', processing: 'info', done: 'success', rejected: 'danger' }[value] || 'info')
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

function handleBusinessLineChange(value) {
  const bizNode = (resourceTree.value || []).find(item => item.node_type === 'biz' && item.name === value)
  const envs = (bizNode?.children || []).map(item => item.name)
  if (!envs.includes(ticketForm.value.environment)) {
    ticketForm.value.environment = envs[0] || ''
  }
}

function handleBizFilterChange(value) {
  if (!value) return
  const envs = envFilterOptions.value.map(item => item.value)
  if (!envs.includes(envFilter.value)) {
    envFilter.value = ''
  }
}

function openCreateDialog() {
  resetTicketForm()
  createVisible.value = true
}

async function createTicket() {
  if (!ticketForm.value.title) return ElMessage.warning('请填写工单标题')
  if (!ticketForm.value.business_line) return ElMessage.warning('请选择业务线')
  if (!ticketForm.value.environment) return ElMessage.warning('请选择环境')

  submitting.value = true
  try {
    await createTransactionTicket(ticketForm.value)
    createVisible.value = false
    ElMessage.success('事务工单已提交')
    await loadTickets()
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, '事务工单提交失败'))
  } finally {
    submitting.value = false
  }
}

async function approveTicket(row) {
  try {
    await approveTransactionTicket(row.id)
    ElMessage.success('工单已审批通过')
    await loadTickets()
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, '审批失败'))
  }
}

async function rejectTicket(row) {
  try {
    await rejectTransactionTicket(row.id)
    ElMessage.success('工单已驳回')
    await loadTickets()
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, '驳回失败'))
  }
}

async function startTicket(row) {
  try {
    await startProcessTransactionTicket(row.id)
    ElMessage.success('工单已进入处理中')
    await loadTickets()
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, '开始处理失败'))
  }
}

async function completeTicket(row) {
  try {
    await completeTransactionTicket(row.id)
    ElMessage.success('工单已完成')
    await loadTickets()
  } catch (error) {
    ElMessage.error(resolveErrorMessage(error, '完成失败'))
  }
}

function viewTicket(row) {
  activeTicket.value = row
  detailVisible.value = true
}

function resolveErrorMessage(error, fallback) {
  const data = error?.response?.data
  if (!data) return fallback
  if (typeof data.detail === 'string' && data.detail) return data.detail
  const first = Object.values(data)[0]
  if (Array.isArray(first) && first[0]) return String(first[0])
  if (typeof first === 'string') return first
  return fallback
}

onMounted(async () => {
  resetTicketForm()
  await Promise.all([loadTickets(), loadFlows(), loadResourceTree()])
})
</script>

<style scoped>
.transaction-ticket-page{display:flex;flex-direction:column;gap:6px}
.panel{background:linear-gradient(180deg,#fff 0%,#f8fbff 100%);border:1px solid rgba(148,163,184,.16);border-radius:20px;box-shadow:0 12px 28px rgba(15,23,42,.05);padding:12px 14px}
.hero{background:linear-gradient(135deg,#f6fbff 0%,#f8fbff 100%);display:flex;gap:12px;justify-content:space-between;align-items:center}
.release-hero-title-row{display:flex;align-items:center;gap:12px}
.release-hero-title-inline{flex-wrap:wrap}
.hero h2{margin:0;color:#0f172a}
.ticket-hero-desc{margin:0;color:#64748b;font-size:13px;line-height:1.5}
.ticket-header-icon{width:42px;height:42px;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;font-size:20px;color:#fff;background:linear-gradient(135deg,#5b8def,#36cfc9);box-shadow:0 10px 20px rgba(64,158,255,.2)}
.hero-actions{display:flex;align-items:center}
.table-card{padding:12px;border-radius:20px;background:rgba(255,255,255,.92);box-shadow:0 12px 26px rgba(15,23,42,.04);border:1px solid rgba(148,163,184,.16)}
.release-stats{gap:8px}
.release-stat-card{position:relative;min-height:76px;background:linear-gradient(145deg,#ffffff 0%,#f6faff 100%);border:1px solid rgba(148,163,184,.16);box-shadow:0 12px 26px rgba(15,23,42,.05);text-align:left;padding:12px 16px;overflow:hidden}
.release-stat-card::after{content:'';position:absolute;inset:auto -24px -30px auto;width:108px;height:108px;border-radius:50%;background:radial-gradient(circle,rgba(64,158,255,.16) 0%,rgba(64,158,255,0) 70%)}
.warning-card::after{background:radial-gradient(circle,rgba(245,158,11,.18) 0%,rgba(245,158,11,0) 70%)}
.success-card::after{background:radial-gradient(circle,rgba(16,185,129,.18) 0%,rgba(16,185,129,0) 70%)}
.danger-card::after{background:radial-gradient(circle,rgba(239,68,68,.18) 0%,rgba(239,68,68,0) 70%)}
.release-stat-card .stat-value{font-size:26px;line-height:1.05}
.release-stat-card .stat-label{margin-top:4px;color:#64748b}
.ticket-alert-strip{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 2px;padding:10px 12px;border-radius:14px;background:rgba(248,250,252,.9);border:1px solid rgba(148,163,184,.18)}
.ticket-alert-strip__label{font-size:12px;font-weight:700;color:#475569}
.ticket-filter-bar{display:flex;align-items:center;gap:10px;flex-wrap:nowrap;overflow-x:auto;padding-bottom:2px;margin-bottom:10px}
.filter-refresh-btn{margin-left:auto;flex-shrink:0}
.stack-cell{display:flex;flex-direction:column;gap:6px}
.ticket-title{font-weight:600;color:#0f172a}
.sub-text{font-size:13px;color:#64748b;line-height:1.5}
.ticket-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 18px}
.ticket-form-grid :deep(.span-2){grid-column:span 2}
@media (max-width: 980px){.ticket-form-grid{grid-template-columns:1fr}.ticket-form-grid :deep(.span-2){grid-column:span 1}.hero{flex-direction:column;align-items:flex-start}}
</style>
