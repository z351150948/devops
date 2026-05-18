<template>
  <div class="fade-in task-workbench-page">
    <section class="hero panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon"><el-icon><Operation /></el-icon></span>
          <h2>任务中心</h2>
          <p class="page-inline-desc">统一承接执行资源、人工下发、AIOps 生成、计划调度和事件联动的任务执行入口。</p>
        </div>
      </div>
      <div class="hero-actions">
        <el-button size="small" :icon="Refresh" :loading="loading" @click="reloadOverview">刷新</el-button>
      </div>
    </section>

    <div class="neo-tabs theme-purple task-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="neo-tab-btn"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        <el-icon style="margin-right: 4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <TaskResourceBase v-if="activeTab === 'assets'" @tree-updated="handleTreeUpdated" @stats-updated="handleResourceStatsUpdated" />
    <CmdbHostTaskCenter v-else-if="activeTab === 'tasks'" :resource-tree="resourceTree" />
    <CmdbHostScheduleCenter v-else :resource-tree="resourceTree" />
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Monitor, Operation, Refresh, Timer } from '@element-plus/icons-vue'
import TaskResourceBase from '@/components/tasks/TaskResourceBase.vue'
import CmdbHostTaskCenter from '@/components/cmdb/CmdbHostTaskCenter.vue'
import CmdbHostScheduleCenter from '@/components/cmdb/CmdbHostScheduleCenter.vue'
import { getHostTaskScheduleStats, getHostTaskStats, getTaskResourceStats, getTaskResourceTree } from '@/api/modules/ops'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const activeTab = ref('tasks')
const resourceTree = ref([])
const resourceStats = ref({ total: 0, host: 0, k8s: 0, active: 0 })
const taskStats = ref({ total: 0, running: 0, pending: 0, success_rate: 0, aiops_pending: 0, high_risk: 0, failed: 0, by_target_type: {} })
const scheduleStats = ref({ total: 0, enabled: 0, due_soon: 0, success_rate: 0 })

const tabs = [
  { key: 'assets', label: '资源底座', icon: Monitor },
  { key: 'tasks', label: '任务工作台', icon: Operation },
  { key: 'schedules', label: '计划任务', icon: Timer },
]

function normalizeTree(list = []) {
  return list.map((env) => ({
    ...env,
    treeKey: `environment:${env.id}`,
    children: (env.children || []).map((system) => ({ ...system, treeKey: `system:${system.id}`, children: [] })),
  }))
}

function handleTreeUpdated(tree) {
  resourceTree.value = normalizeTree(tree)
}

function handleResourceStatsUpdated(stats) {
  resourceStats.value = stats || resourceStats.value
}

async function reloadOverview() {
  loading.value = true
  try {
    const [tree, resources, tasks, schedules] = await Promise.all([
      getTaskResourceTree(),
      getTaskResourceStats(),
      getHostTaskStats(),
      getHostTaskScheduleStats(),
    ])
    resourceTree.value = normalizeTree(tree || [])
    resourceStats.value = resources || resourceStats.value
    taskStats.value = tasks || taskStats.value
    scheduleStats.value = schedules || scheduleStats.value
  } finally {
    loading.value = false
  }
}

function syncTabFromRoute() {
  const next = String(route.query.tab || 'tasks')
  activeTab.value = tabs.some((item) => item.key === next) ? next : 'tasks'
}

watch(() => route.query.tab, syncTabFromRoute, { immediate: true })
watch(activeTab, (tab) => {
  if (route.query.tab !== tab) {
    const query = { ...route.query }
    if (tab === 'tasks') delete query.tab
    else query.tab = tab
    router.replace({ path: '/tasks', query })
  }
})

onMounted(reloadOverview)
</script>

<style scoped>
.task-workbench-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hero,
.hero-title-row,
.hero-actions {
  align-items: center;
  display: flex;
  gap: 4px;
}

.hero.panel {
  background: linear-gradient(180deg, #ffffff 0%, #fffdf8 100%);
  border: 1px solid #eff0f2;
  border-radius: 12px;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
  justify-content: space-between;
  padding: 12px 14px;
}

.hero-copy {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.hero-title-row {
  align-items: baseline;
  gap: 10px;
}

.hero-title-row h2 {
  color: #0f172a;
  font-size: 23px;
  font-weight: 700;
  line-height: 1.1;
  margin: 0;
}

.page-inline-desc {
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
  margin: 0;
}

.hero-icon {
  align-items: center;
  background: linear-gradient(135deg, #0f766e, #0ea5e9);
  border-radius: 16px;
  color: #fff;
  display: inline-flex;
  font-size: 20px;
  height: 40px;
  justify-content: center;
  width: 40px;
}

.hero-actions .el-button {
  border-radius: 10px;
  font-weight: 500;
  min-height: 32px;
  padding: 0 14px;
}

.panel {
  background: #fff;
  border: 1px solid #eff0f2;
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(31, 35, 41, 0.06);
  padding: 12px 14px;
}

.task-tabs {
  width: 100%;
  padding: 4px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.04);
}

@media (max-width: 760px) {
  .hero.panel {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
