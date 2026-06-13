<template>
  <div class="metrics-page workbench-page-shell">
    <section class="hero panel">
      <div class="release-hero-copy">
        <div class="release-hero-title-row release-hero-title-inline">
          <span class="release-header-icon"><el-icon><DataAnalysis /></el-icon></span>
          <h2>指标查询</h2>
          <p class="page-inline-desc">Prometheus 兼容数据源、PromQL 查询与环境关联入口</p>
        </div>
      </div>
    </section>

    <div class="audit-grid">
      <button type="button" class="audit-card audit-card--inline audit-card--action" :class="{ 'is-active': activeTab === 'query' }" @click="activeTab = 'query'">
        <div class="stat-value">{{ dataSources.length }}</div>
        <div class="stat-label">数据源</div>
      </button>
      <button type="button" class="audit-card audit-card--inline audit-card--success audit-card--action" :class="{ 'is-active': activeTab === 'datasources' }" @click="activeTab = 'datasources'">
        <div class="stat-value">{{ enabledCount }}</div>
        <div class="stat-label">启用中</div>
      </button>
      <div class="audit-card audit-card--inline">
        <div class="stat-value">{{ lastResult.series_count ?? 0 }}</div>
        <div class="stat-label">结果序列</div>
      </div>
      <div class="audit-card audit-card--inline" :class="lastQueryFailed ? 'audit-card--danger' : 'audit-card--warning'">
        <div class="stat-value">{{ lastQueryDuration ? `${lastQueryDuration}ms` : '--' }}</div>
        <div class="stat-label">{{ lastQueryFailed ? '最近失败' : '最近耗时' }}</div>
      </div>
    </div>

    <div class="neo-tabs theme-blue metrics-tabs">
      <button class="neo-tab-btn" :class="{ active: activeTab === 'query' }" @click="activeTab = 'query'">
        <el-icon><Search /></el-icon>
        PromQL 查询
      </button>
      <button class="neo-tab-btn" :class="{ active: activeTab === 'datasources' }" @click="activeTab = 'datasources'">
        <el-icon><DataBoard /></el-icon>
        数据源
      </button>
    </div>

    <section v-if="activeTab === 'query'" class="workbench-card query-card">
      <div class="section-toolbar">
        <div class="toolbar-head">
          <span class="toolbar-title">PromQL 查询</span>
          <span class="toolbar-desc">优先使用选中的指标数据源，未选择时按后端环境默认规则解析。</span>
        </div>
        <div class="workbench-card-actions">
          <el-button @click="loadDataSources" :loading="loadingSources">
            <el-icon><RefreshRight /></el-icon>
            刷新
          </el-button>
          <el-button type="primary" :loading="queryLoading" :disabled="!canQuery" @click="runQuery">
            <el-icon><CaretRight /></el-icon>
            执行查询
          </el-button>
        </div>
      </div>

      <div class="workbench-toolbar workbench-toolbar--history query-toolbar">
        <div class="workbench-toolbar-left">
          <el-select v-model="queryForm.metric_datasource_id" clearable filterable placeholder="指标数据源" style="width: 220px">
            <el-option v-for="item in dataSources" :key="item.id" :label="sourceOptionLabel(item)" :value="item.id" />
          </el-select>
          <el-input v-model.trim="queryForm.environment" clearable placeholder="环境，可选" style="width: 150px" />
          <el-segmented v-model="queryForm.mode" :options="modeOptions" />
          <el-date-picker
            v-if="queryForm.mode === 'range'"
            v-model="queryForm.timeRange"
            type="datetimerange"
            format="YYYY-MM-DD HH:mm:ss"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            :shortcuts="timeShortcuts"
            style="width: 350px"
          />
          <el-input-number v-if="queryForm.mode === 'range'" v-model="queryForm.step" :min="1" :max="3600" :step="15" controls-position="right" style="width: 118px" />
        </div>
        <div class="workbench-toolbar-right">
          <el-button v-for="sample in promqlSamples" :key="sample" text type="primary" @click="queryForm.promql = sample">{{ sample }}</el-button>
        </div>
      </div>

      <div class="query-editor">
        <el-input
          v-model="queryForm.promql"
          type="textarea"
          :rows="4"
          resize="vertical"
          placeholder='例如：up 或 sum(rate(http_requests_total[5m])) by (service)'
        />
      </div>

      <div class="result-strip">
        <span class="query-pill">来源：{{ lastResultSource }}</span>
        <span class="query-pill">类型：{{ lastResult.resultType || '--' }}</span>
        <span class="query-pill">序列：{{ lastResult.series_count ?? 0 }}</span>
        <span class="query-pill">步长：{{ lastResult.step || queryForm.step }}s</span>
      </div>

      <el-alert v-if="queryError" :title="queryError" type="error" show-icon :closable="false" />
      <el-empty v-else-if="!resultRows.length && !queryLoading" description="暂无查询结果，输入 PromQL 后执行。" />
      <el-table v-else v-loading="queryLoading" :data="resultRows" stripe class="result-table">
        <el-table-column prop="metricText" label="标签" min-width="300" show-overflow-tooltip />
        <el-table-column prop="latestValue" label="最新值" min-width="160" />
        <el-table-column prop="points" label="点数" width="90" />
        <el-table-column prop="timestamp" label="时间" width="180" />
      </el-table>

      <el-collapse v-if="Object.keys(lastResult).length" class="raw-collapse">
        <el-collapse-item title="原始响应" name="raw">
          <pre class="raw-json">{{ formattedResult }}</pre>
        </el-collapse-item>
      </el-collapse>
    </section>

    <section v-else class="workbench-card">
      <div class="section-toolbar">
        <div class="toolbar-head">
          <span class="toolbar-title">指标数据源</span>
          <span class="toolbar-desc">支持 Prometheus HTTP API，兼容夜莺 prometheus.addr / headers / basic 配置语义。</span>
        </div>
        <div class="workbench-card-actions">
          <el-button @click="loadDataSources" :loading="loadingSources">
            <el-icon><RefreshRight /></el-icon>
            刷新
          </el-button>
          <el-button v-if="canManageDatasource" type="primary" @click="openDatasourceDialog()">
            <el-icon><Plus /></el-icon>
            新增数据源
          </el-button>
        </div>
      </div>

      <div class="workbench-toolbar workbench-toolbar--history">
        <div class="workbench-toolbar-left">
          <el-input v-model.trim="filters.keyword" clearable placeholder="搜索名称 / 环境 / 地址" style="width: 260px" />
          <el-select v-model="filters.enabled" clearable placeholder="状态" style="width: 110px">
            <el-option label="启用" value="true" />
            <el-option label="停用" value="false" />
          </el-select>
        </div>
        <div class="workbench-toolbar-right">
          <span class="toolbar-count">共 {{ filteredDataSources.length }} 个</span>
        </div>
      </div>

      <el-table v-loading="loadingSources" :data="filteredDataSources" stripe>
        <el-table-column label="名称" min-width="210">
          <template #default="{ row }">
            <div class="source-name">{{ row.name }}</div>
            <div class="source-desc">{{ row.description || endpointOf(row) || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="environment" label="环境" width="120">
          <template #default="{ row }">{{ row.environment || '全局' }}</template>
        </el-table-column>
        <el-table-column prop="cluster_name" label="集群" min-width="140" show-overflow-tooltip />
        <el-table-column label="类型" width="130">
          <template #default="{ row }">{{ row.provider_display || row.provider }}</template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
            <el-tag v-if="row.is_default" size="small" type="warning" class="ml-6">默认</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="canManageDatasource" label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="testSource(row)">测试</el-button>
            <el-button link type="primary" size="small" @click="openDatasourceDialog(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="removeSource(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialog.visible" :title="dialog.editingId ? '编辑指标数据源' : '新增指标数据源'" width="720px" append-to-body destroy-on-close>
      <el-form ref="sourceFormRef" :model="sourceForm" :rules="sourceRules" label-width="124px">
        <el-form-item label="名称" prop="name">
          <el-input v-model.trim="sourceForm.name" placeholder="例如：电商测试 Prometheus" />
        </el-form-item>
        <el-form-item label="环境">
          <el-input v-model.trim="sourceForm.environment" placeholder="例如：电商测试环境；留空表示全局" />
        </el-form-item>
        <el-form-item label="查询地址" prop="query_url">
          <el-input v-model.trim="sourceForm.query_url" placeholder="http://prometheus:9090" />
        </el-form-item>
        <el-form-item label="集群 / TSDB">
          <div class="inline-fields">
            <el-input v-model.trim="sourceForm.cluster_name" placeholder="cluster_name" />
            <el-input v-model.trim="sourceForm.tsdb_type" placeholder="prometheus" />
          </div>
        </el-form-item>
        <el-form-item label="认证方式">
          <el-select v-model="sourceForm.auth_type" style="width: 180px">
            <el-option label="无认证" value="none" />
            <el-option label="Basic" value="basic" />
            <el-option label="Bearer Token" value="bearer" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="sourceForm.auth_type === 'basic'" label="Basic 账号">
          <div class="inline-fields">
            <el-input v-model.trim="sourceForm.username" placeholder="用户名" />
            <el-input v-model="sourceForm.password" type="password" show-password placeholder="密码；已配置可留 configured" />
          </div>
        </el-form-item>
        <el-form-item v-if="sourceForm.auth_type === 'bearer'" label="Bearer Token">
          <el-input v-model="sourceForm.bearer_token" type="password" show-password placeholder="已配置可保留 configured" />
        </el-form-item>
        <el-form-item label="Headers JSON">
          <el-input v-model="sourceForm.headersText" type="textarea" :rows="3" placeholder='{"X-Scope-OrgID":"team-a"}' />
        </el-form-item>
        <el-form-item label="连接参数">
          <div class="inline-fields inline-fields--small">
            <el-input-number v-model="sourceForm.timeout" :min="1" :max="60" controls-position="right" />
            <el-checkbox v-model="sourceForm.tls_skip_verify">跳过 TLS 校验</el-checkbox>
            <el-checkbox v-model="sourceForm.is_default">设为默认</el-checkbox>
            <el-switch v-model="sourceForm.is_enabled" inline-prompt active-text="启用" inactive-text="停用" />
          </div>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model.trim="sourceForm.description" maxlength="255" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="savingSource" @click="submitDatasource">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CaretRight, DataAnalysis, DataBoard, Plus, RefreshRight, Search } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  createMetricDataSource,
  deleteMetricDataSource,
  getMetricDataSources,
  queryMetrics,
  testMetricDataSource,
  updateMetricDataSource,
} from '@/api/modules/ops'

const authStore = useAuthStore()
const canQuery = computed(() => authStore.hasPermission('ops.metric.query'))
const canManageDatasource = computed(() => authStore.hasPermission('ops.metric.datasource.manage'))
const activeTab = ref('query')
const loadingSources = ref(false)
const queryLoading = ref(false)
const savingSource = ref(false)
const dataSources = ref([])
const lastResult = ref({})
const queryError = ref('')
const lastQueryDuration = ref(0)
const lastQueryFailed = ref(false)
const sourceFormRef = ref(null)

const modeOptions = [
  { label: '即时', value: 'instant' },
  { label: '区间', value: 'range' },
]
const now = Date.now()
const queryForm = reactive({
  metric_datasource_id: '',
  environment: '',
  mode: 'range',
  step: 60,
  promql: 'up',
  timeRange: [new Date(now - 30 * 60 * 1000), new Date(now)],
})
const filters = reactive({ keyword: '', enabled: '' })
const dialog = reactive({ visible: false, editingId: null })
const sourceForm = reactive({
  name: '',
  provider: 'prometheus',
  description: '',
  environment: '',
  cluster_name: '',
  tsdb_type: 'prometheus',
  query_url: '',
  auth_type: 'none',
  username: '',
  password: '',
  bearer_token: '',
  headersText: '',
  timeout: 6,
  tls_skip_verify: false,
  is_enabled: true,
  is_default: false,
})
const sourceRules = {
  name: [{ required: true, message: '请填写数据源名称', trigger: 'blur' }],
  query_url: [{ required: true, message: '请填写 Prometheus 查询地址', trigger: 'blur' }],
}
const timeShortcuts = [
  { text: '最近 15 分钟', value: () => [new Date(Date.now() - 15 * 60 * 1000), new Date()] },
  { text: '最近 30 分钟', value: () => [new Date(Date.now() - 30 * 60 * 1000), new Date()] },
  { text: '最近 1 小时', value: () => [new Date(Date.now() - 60 * 60 * 1000), new Date()] },
]
const promqlSamples = ['up', 'sum(rate(http_requests_total[5m]))', 'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))']

const enabledCount = computed(() => dataSources.value.filter(item => item.is_enabled).length)
const filteredDataSources = computed(() => {
  const keyword = filters.keyword.toLowerCase()
  return dataSources.value.filter((item) => {
    const enabledMatched = !filters.enabled || String(Boolean(item.is_enabled)) === filters.enabled
    const text = `${item.name} ${item.environment || ''} ${item.cluster_name || ''} ${endpointOf(item) || ''}`.toLowerCase()
    return enabledMatched && (!keyword || text.includes(keyword))
  })
})
const lastResultSource = computed(() => {
  const ds = lastResult.value.metric_datasource
  if (ds?.name) return ds.name
  return lastResult.value.description || lastResult.value.source || '--'
})
const resultRows = computed(() => (lastResult.value.result || []).map((item, index) => {
  const values = item.values || []
  const latest = values.length ? values[values.length - 1] : item.value
  const metric = item.metric || {}
  return {
    id: index,
    metricText: Object.keys(metric).length ? Object.entries(metric).map(([key, value]) => `${key}="${value}"`).join(', ') : 'scalar',
    latestValue: Array.isArray(latest) ? latest[1] : latest,
    timestamp: Array.isArray(latest) ? formatTimestamp(latest[0]) : '--',
    points: values.length || (item.value ? 1 : 0),
  }
}))
const formattedResult = computed(() => JSON.stringify(lastResult.value, null, 2))

function endpointOf(row) {
  return row?.config?.query_url || row?.config?.['prometheus.addr'] || row?.config?.addr || ''
}

function sourceOptionLabel(item) {
  const env = item.environment ? ` / ${item.environment}` : ' / 全局'
  return `${item.name}${env}`
}

function formatTimestamp(value) {
  const timestamp = Number(value)
  if (!Number.isFinite(timestamp)) return '--'
  return new Date(timestamp * 1000).toLocaleString()
}

function resetSourceForm(row = null) {
  const config = row?.config || {}
  dialog.editingId = row?.id || null
  sourceForm.name = row?.name || ''
  sourceForm.provider = row?.provider || 'prometheus'
  sourceForm.description = row?.description || ''
  sourceForm.environment = row?.environment || ''
  sourceForm.cluster_name = row?.cluster_name || ''
  sourceForm.tsdb_type = row?.tsdb_type || 'prometheus'
  sourceForm.query_url = config.query_url || config['prometheus.addr'] || ''
  sourceForm.auth_type = config.auth_type || 'none'
  sourceForm.username = config.username || config['prometheus.basic']?.['prometheus.user'] || ''
  sourceForm.password = config.password || config['prometheus.basic']?.['prometheus.password'] || ''
  sourceForm.bearer_token = config.bearer_token || ''
  sourceForm.headersText = JSON.stringify(config.headers || config['prometheus.headers'] || {}, null, 2)
  sourceForm.timeout = Number(config.timeout || config['prometheus.timeout'] || 6)
  sourceForm.tls_skip_verify = Boolean(config.tls_skip_verify)
  sourceForm.is_enabled = row?.is_enabled ?? true
  sourceForm.is_default = row?.is_default ?? false
}

function buildSourcePayload() {
  let headers = {}
  if (sourceForm.headersText.trim()) {
    headers = JSON.parse(sourceForm.headersText)
    if (!headers || typeof headers !== 'object' || Array.isArray(headers)) {
      throw new Error('Headers JSON 必须是对象')
    }
  }
  return {
    name: sourceForm.name,
    provider: sourceForm.provider,
    description: sourceForm.description,
    environment: sourceForm.environment,
    cluster_name: sourceForm.cluster_name,
    tsdb_type: sourceForm.tsdb_type || 'prometheus',
    is_enabled: sourceForm.is_enabled,
    is_default: sourceForm.is_default,
    config: {
      query_url: sourceForm.query_url,
      'prometheus.addr': sourceForm.query_url,
      auth_type: sourceForm.auth_type,
      username: sourceForm.username,
      password: sourceForm.password,
      bearer_token: sourceForm.bearer_token,
      headers,
      'prometheus.headers': headers,
      timeout: sourceForm.timeout,
      'prometheus.timeout': sourceForm.timeout,
      tls_skip_verify: sourceForm.tls_skip_verify,
      'prometheus.basic': {
        'prometheus.user': sourceForm.username,
        'prometheus.password': sourceForm.password,
      },
    },
  }
}

async function loadDataSources() {
  loadingSources.value = true
  try {
    const response = await getMetricDataSources()
    dataSources.value = Array.isArray(response) ? response : (response.results || [])
    if (!queryForm.metric_datasource_id && dataSources.value.length) {
      const defaultSource = dataSources.value.find(item => item.is_default && item.is_enabled) || dataSources.value.find(item => item.is_enabled)
      queryForm.metric_datasource_id = defaultSource?.id || ''
    }
  } finally {
    loadingSources.value = false
  }
}

async function runQuery() {
  if (!queryForm.promql.trim()) {
    ElMessage.warning('请填写 PromQL')
    return
  }
  queryLoading.value = true
  queryError.value = ''
  lastQueryFailed.value = false
  const startedAt = performance.now()
  try {
    const payload = {
      promql: queryForm.promql,
      metric_datasource_id: queryForm.metric_datasource_id || '',
      environment: queryForm.environment,
      range_query: queryForm.mode === 'range',
      step: queryForm.step,
    }
    if (queryForm.mode === 'range' && queryForm.timeRange?.length === 2) {
      payload.start = queryForm.timeRange[0].toISOString()
      payload.end = queryForm.timeRange[1].toISOString()
    }
    lastResult.value = await queryMetrics(payload)
    lastQueryDuration.value = Math.round(performance.now() - startedAt)
  } catch (error) {
    lastQueryFailed.value = true
    queryError.value = error?.response?.data?.detail || error.message || '指标查询失败'
  } finally {
    queryLoading.value = false
  }
}

function openDatasourceDialog(row = null) {
  resetSourceForm(row)
  dialog.visible = true
}

async function submitDatasource() {
  await sourceFormRef.value?.validate()
  savingSource.value = true
  try {
    const payload = buildSourcePayload()
    if (dialog.editingId) {
      await updateMetricDataSource(dialog.editingId, payload)
    } else {
      await createMetricDataSource(payload)
    }
    ElMessage.success('指标数据源已保存')
    dialog.visible = false
    await loadDataSources()
  } catch (error) {
    if (error instanceof SyntaxError || error.message?.includes('Headers JSON')) {
      ElMessage.error(error.message || 'Headers JSON 格式不正确')
    } else {
      throw error
    }
  } finally {
    savingSource.value = false
  }
}

async function testSource(row) {
  const response = await testMetricDataSource(row.id, { query: 'up' })
  ElMessage.success(`${response.message || '连接成功'}，返回 ${response.series_count || 0} 条序列`)
}

async function removeSource(row) {
  await ElMessageBox.confirm(`确认删除指标数据源「${row.name}」？`, '删除确认', { type: 'warning' })
  await deleteMetricDataSource(row.id)
  ElMessage.success('指标数据源已删除')
  await loadDataSources()
}

onMounted(loadDataSources)
</script>

<style scoped>
.metrics-page {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.panel,
.workbench-card {
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 14px;
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.04);
}

.hero.panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-radius: 20px;
  background: linear-gradient(135deg, #fbfdff 0%, #f7faff 52%, #f9fbfd 100%);
  border-color: rgba(36, 91, 219, 0.09);
}

.release-hero-title-row,
.release-hero-title-inline {
  display: flex;
  align-items: center;
  gap: 10px;
}

.release-hero-title-row h2 {
  margin: 0;
  color: #0f172a;
  font-size: 23px;
  font-weight: 800;
}

.release-header-icon {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #245bdb;
  background: #eaf2ff;
}

.page-inline-desc {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.audit-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.audit-card {
  min-height: 68px;
  padding: 14px 16px;
  text-align: left;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.04);
}

.audit-card--action {
  cursor: pointer;
}

.audit-card.is-active {
  border-color: rgba(51, 112, 255, 0.28);
  background: #e8f0ff;
}

.audit-card--success {
  background: linear-gradient(180deg, #ecfdf5 0%, #fff 100%);
}

.audit-card--warning {
  background: linear-gradient(180deg, #fff7ed 0%, #fff 100%);
}

.audit-card--danger {
  background: linear-gradient(180deg, #fef2f2 0%, #fff 100%);
}

.stat-value {
  color: #0f172a;
  font-size: 24px;
  font-weight: 800;
}

.stat-label,
.source-desc,
.toolbar-count {
  color: #64748b;
  font-size: 13px;
}

.metrics-tabs {
  display: flex;
  width: 100%;
  padding: 3px;
  gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.04);
}

.neo-tab-btn {
  min-height: 38px;
  padding: 0 18px;
  border: 0;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #475569;
  background: transparent;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.neo-tab-btn.active {
  color: #245bdb;
  background: rgba(51, 112, 255, 0.1);
  box-shadow: inset 0 0 0 1px rgba(51, 112, 255, 0.14);
}

.workbench-card {
  padding: 12px 14px;
}

.section-toolbar,
.toolbar-head,
.workbench-card-actions,
.workbench-toolbar,
.workbench-toolbar-left,
.workbench-toolbar-right {
  display: flex;
  align-items: center;
}

.section-toolbar {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.toolbar-head {
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar-title {
  color: #0f172a;
  font-size: 15px;
  font-weight: 800;
}

.toolbar-desc {
  color: #64748b;
  font-size: 13px;
}

.workbench-card-actions,
.workbench-toolbar-left,
.workbench-toolbar-right {
  gap: 8px;
}

.workbench-toolbar {
  justify-content: space-between;
  gap: 12px;
  padding: 10px;
  margin-bottom: 10px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.88);
}

.query-toolbar {
  align-items: flex-start;
}

.query-editor {
  margin-bottom: 10px;
}

.result-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.query-pill {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 999px;
  color: #475569;
  background: #fff;
  font-size: 12px;
}

.result-table {
  margin-top: 8px;
}

.raw-collapse {
  margin-top: 10px;
}

.raw-json {
  max-height: 360px;
  overflow: auto;
  padding: 10px;
  border-radius: 10px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 12px;
}

.source-name {
  color: #0f172a;
  font-weight: 700;
}

.ml-6 {
  margin-left: 6px;
}

.inline-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}

.inline-fields--small {
  grid-template-columns: 120px auto auto auto;
  align-items: center;
}

@media (max-width: 960px) {
  .audit-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .section-toolbar,
  .workbench-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .workbench-toolbar-left,
  .workbench-toolbar-right,
  .inline-fields,
  .inline-fields--small {
    grid-template-columns: 1fr;
    flex-wrap: wrap;
  }
}
</style>
