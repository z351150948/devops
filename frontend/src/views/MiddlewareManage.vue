<template>
  <div class="fade-in middleware-page" :class="`middleware-page--${moduleKey}`">
    <div class="page-header middleware-header">
      <div>
        <div class="module-badge">{{ moduleMeta.badge }}</div>
        <h2>{{ moduleMeta.title }}</h2>
        <p class="page-subtitle">{{ moduleMeta.subtitle }}</p>
      </div>
      <div class="header-actions">
        <el-tag effect="plain" :type="statusTagType(moduleStatus)">状态：{{ moduleStatusLabel }}</el-tag>
        <el-tag type="info" effect="plain">最近更新：{{ formattedUpdatedAt }}</el-tag>
        <el-button :loading="loading" @click="refreshData">
          <el-icon><RefreshRight /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <div class="module-banner">
      <div class="module-banner__title">{{ moduleMeta.bannerTitle }}</div>
      <div class="module-banner__desc">{{ moduleMeta.bannerDesc }}</div>
    </div>

    <div v-if="currentAlerts.length" class="middleware-alert-strip">
      <span class="middleware-alert-strip__label">运行提示</span>
      <el-tag
        v-for="(alert, index) in currentAlerts.slice(0, 2)"
        :key="`${alert.title}-${index}`"
        size="small"
        effect="light"
        :type="summaryAlertTagType(alert.level)"
        class="middleware-alert-strip__tag"
      >
        {{ compactAlertMessage(alert.message) }}
      </el-tag>
      <el-popover v-if="currentAlerts.length > 2" placement="bottom-end" :width="320" trigger="hover">
        <template #reference>
          <el-button link type="primary">+{{ currentAlerts.length - 2 }} 更多</el-button>
        </template>
        <div class="alert-popover">
          <div v-for="(alert, index) in currentAlerts" :key="`all-${index}`" class="alert-popover__item">
            <el-tag size="small" :type="summaryAlertTagType(alert.level)">{{ alert.title }}</el-tag>
            <span>{{ alert.message }}</span>
          </div>
        </div>
      </el-popover>
    </div>

    <div class="module-summary-grid">
      <div v-for="card in summaryCards" :key="card.label" class="module-summary-card">
        <span class="module-summary-label">{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <span class="module-summary-meta">{{ card.meta }}</span>
      </div>
    </div>

    <div class="neo-tabs theme-blue middleware-tabs">
      <button v-for="tab in mainTabs" :key="tab.key" class="neo-tab-btn" :class="{ active: activeTab === tab.key }" @click="switchTab(tab.key)">
        <el-icon style="margin-right:4px;"><component :is="tab.icon" /></el-icon>
        {{ tab.label }}
      </button>
    </div>

    <el-card shadow="never" class="section-card toolbar-card">
      <div class="toolbar-grid">
        <el-input v-model="filters.search" clearable :placeholder="searchPlaceholder" class="toolbar-control" />
        <el-select v-model="filters.environment" class="toolbar-control">
          <el-option label="全部环境" value="all" />
          <el-option v-for="item in environmentOptions" :key="item" :label="item" :value="item" />
        </el-select>
        <el-select v-model="filters.state" class="toolbar-control">
          <el-option v-for="item in stateOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <div class="toolbar-actions">
          <el-button v-if="canManageMiddleware && activeTab === 'clusters'" type="primary" @click="openClusterDialog">
            <el-icon><Plus /></el-icon>
            新增集群
          </el-button>
          <el-button v-if="canManageMiddleware && activeTab === 'instances'" type="primary" @click="openInstanceDialog">
            <el-icon><Plus /></el-icon>
            {{ instanceButtonLabel }}
          </el-button>
        </div>
      </div>
    </el-card>

    <template v-if="moduleKey === 'redis'">
      <el-card v-if="activeTab === 'clusters'" shadow="never" class="section-card">
        <template #header><div class="section-title">Redis 集群管理</div></template>
        <el-table :data="filteredRedisClusters" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="集群" min-width="160" />
          <el-table-column prop="environment" label="环境" width="90" />
          <el-table-column prop="status" label="状态" width="100">
            <template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag></template>
          </el-table-column>
          <el-table-column prop="mode" label="模式" min-width="140" />
          <el-table-column prop="slot_coverage" label="槽位覆盖" width="120" />
          <el-table-column label="资源" min-width="180">
            <template #default="{ row }"><div>内存 {{ row.memory_total_gb }} GB</div><div>命中率 {{ row.hit_rate }}%</div></template>
          </el-table-column>
          <el-table-column label="吞吐" width="140"><template #default="{ row }">{{ formatNumber(row.ops_per_sec) }} ops/s</template></el-table-column>
        </el-table>
      </el-card>

      <el-card v-if="activeTab === 'instances'" shadow="never" class="section-card">
        <template #header><div class="section-title">Redis 实例管理</div></template>
        <el-table :data="filteredRedisInstances" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="实例" min-width="170" />
          <el-table-column prop="cluster" label="集群" min-width="140" />
          <el-table-column prop="environment" label="环境" width="90" />
          <el-table-column prop="role" label="角色" width="100"><template #default="{ row }"><el-tag :type="row.role === 'master' ? 'danger' : 'success'" size="small">{{ row.role }}</el-tag></template></el-table-column>
          <el-table-column prop="endpoint" label="地址" min-width="170" />
          <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column label="负载" min-width="150"><template #default="{ row }"><div>QPS {{ formatNumber(row.qps) }}</div><div>连接 {{ formatNumber(row.connections) }}</div></template></el-table-column>
          <el-table-column label="复制 / 持久化" min-width="160"><template #default="{ row }"><div>延迟 {{ row.replication_delay_ms }}ms</div><div>{{ row.persistence }}</div></template></el-table-column>
          <el-table-column prop="last_sync" label="最近同步" width="150" />
          <el-table-column v-if="canManageMiddleware" label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :loading="isActing('redis', row.id, 'restart')" @click="handleAction('redis', row.id, 'restart')">重启</el-button>
              <el-button v-if="row.role === 'replica'" link type="warning" :loading="isActing('redis', row.id, 'promote')" @click="handleAction('redis', row.id, 'promote')">提升主库</el-button>
              <el-button v-if="row.role === 'replica'" link type="success" :loading="isActing('redis', row.id, 'resync')" @click="handleAction('redis', row.id, 'resync')">重同步</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <div v-if="activeTab === 'runtime'" class="dual-grid">
        <el-card shadow="never" class="section-card">
          <template #header><div class="section-title">热点 Key 风险</div></template>
          <el-table :data="filteredRedisHotKeys" stripe style="width: 100%" v-loading="loading">
            <el-table-column prop="key" label="Key" min-width="210" />
            <el-table-column prop="cluster" label="集群" min-width="120" />
            <el-table-column prop="ops_per_sec" label="OPS/s" width="100"><template #default="{ row }">{{ formatNumber(row.ops_per_sec) }}</template></el-table-column>
            <el-table-column prop="memory_kb" label="内存" width="100"><template #default="{ row }">{{ formatNumber(row.memory_kb) }} KB</template></el-table-column>
            <el-table-column prop="risk" label="风险" width="100"><template #default="{ row }"><el-tag :type="riskTagType(row.risk)" size="small">{{ row.risk }}</el-tag></template></el-table-column>
          </el-table>
        </el-card>
        <el-card shadow="never" class="section-card">
          <template #header><div class="section-title">运行事件</div></template>
          <div class="timeline-list">
            <div v-for="event in redis.events || []" :key="event.id" class="timeline-item">
              <div class="timeline-dot" :class="`timeline-dot--${event.level}`"></div>
              <div class="timeline-content"><div class="timeline-top"><span class="timeline-title">{{ event.title }}</span><span class="timeline-time">{{ event.time }}</span></div><div class="timeline-detail">{{ event.detail }}</div></div>
            </div>
          </div>
        </el-card>
      </div>
    </template>

    <template v-else-if="moduleKey === 'rocketmq'">
      <el-card v-if="activeTab === 'clusters'" shadow="never" class="section-card">
        <template #header><div class="section-title">RocketMQ 集群管理</div></template>
        <el-table :data="filteredRocketmqClusters" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="集群" min-width="150" />
          <el-table-column prop="environment" label="环境" width="90" />
          <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column label="规模" min-width="140"><template #default="{ row }"><div>NameServer {{ row.nameserver_count }}</div><div>Broker {{ row.broker_count }}</div></template></el-table-column>
          <el-table-column label="吞吐" width="120"><template #default="{ row }">{{ formatNumber(row.tps) }} TPS</template></el-table-column>
          <el-table-column prop="topic_count" label="Topic 数" width="110" />
        </el-table>
      </el-card>

      <el-card v-if="activeTab === 'instances'" shadow="never" class="section-card">
        <template #header><div class="section-title">Broker 管理</div></template>
        <el-table :data="filteredRocketmqBrokers" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="Broker" min-width="140" />
          <el-table-column prop="cluster" label="集群" min-width="120" />
          <el-table-column prop="environment" label="环境" width="90" />
          <el-table-column prop="role" label="角色" width="100"><template #default="{ row }"><el-tag :type="row.role === 'master' ? 'danger' : 'info'" size="small">{{ row.role }}</el-tag></template></el-table-column>
          <el-table-column prop="endpoint" label="地址" min-width="170" />
          <el-table-column label="负载" min-width="150"><template #default="{ row }"><div>TPS {{ formatNumber(row.tps) }}</div><div>Topic {{ row.topic_count }}</div></template></el-table-column>
          <el-table-column label="容量" min-width="150"><template #default="{ row }"><div>磁盘 {{ row.disk_usage }}%</div><div>积压 {{ formatNumber(row.consumer_lag) }}</div></template></el-table-column>
          <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column v-if="canManageMiddleware" label="操作" width="180" fixed="right"><template #default="{ row }"><el-button link type="primary" :loading="isActing('rocketmq', row.id, 'restart')" @click="handleAction('rocketmq', row.id, 'restart')">重启</el-button><el-button link type="warning" :loading="isActing('rocketmq', row.id, 'rebalance')" @click="handleAction('rocketmq', row.id, 'rebalance')">Rebalance</el-button></template></el-table-column>
        </el-table>
      </el-card>

      <div v-if="activeTab === 'runtime'" class="stack-grid">
        <div class="dual-grid">
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">消费组积压</div></template>
            <el-table :data="filteredRocketmqGroups" stripe style="width: 100%" v-loading="loading">
              <el-table-column prop="group" label="消费组" min-width="150" />
              <el-table-column prop="cluster" label="集群" min-width="110" />
              <el-table-column prop="topic" label="Topic" min-width="160" />
              <el-table-column prop="clients" label="客户端" width="88" />
              <el-table-column prop="retry" label="重试" width="80" />
              <el-table-column prop="lag" label="积压" width="100"><template #default="{ row }"><span :class="{ 'warning-text': row.lag >= 1000 }">{{ formatNumber(row.lag) }}</span></template></el-table-column>
            </el-table>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">Topic 演示数据</div></template>
            <el-table :data="filteredRocketmqTopics" stripe style="width: 100%" v-loading="loading">
              <el-table-column prop="name" label="Topic" min-width="180" />
              <el-table-column prop="cluster" label="集群" min-width="110" />
              <el-table-column prop="messages_24h" label="24h 消息量" width="120" />
              <el-table-column prop="retention_hours" label="保留时长" width="110"><template #default="{ row }">{{ row.retention_hours }} h</template></el-table-column>
              <el-table-column prop="dead_letter" label="死信" width="90"><template #default="{ row }"><span :class="{ 'warning-text': row.dead_letter >= 100 }">{{ row.dead_letter }}</span></template></el-table-column>
            </el-table>
          </el-card>
        </div>
        <el-card shadow="never" class="section-card">
          <template #header><div class="section-title">运行事件</div></template>
          <div class="timeline-list">
            <div v-for="event in rocketmq.events || []" :key="event.id" class="timeline-item"><div class="timeline-dot" :class="`timeline-dot--${event.level}`"></div><div class="timeline-content"><div class="timeline-top"><span class="timeline-title">{{ event.title }}</span><span class="timeline-time">{{ event.time }}</span></div><div class="timeline-detail">{{ event.detail }}</div></div></div>
          </div>
        </el-card>
      </div>
    </template>

    <template v-else>
      <el-card v-if="activeTab === 'clusters'" shadow="never" class="section-card">
        <template #header><div class="section-title">Elasticsearch 集群管理</div></template>
        <el-table :data="filteredEsClusters" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="集群" min-width="150" />
          <el-table-column prop="environment" label="环境" width="90" />
          <el-table-column prop="health" label="健康度" width="100"><template #default="{ row }"><el-tag :type="healthTagType(row.health)" size="small">{{ row.health }}</el-tag></template></el-table-column>
          <el-table-column prop="nodes" label="节点数" width="90" />
          <el-table-column prop="indices" label="索引数" width="90" />
          <el-table-column prop="storage" label="存储" width="110" />
          <el-table-column label="查询能力" min-width="160"><template #default="{ row }"><div>QPS {{ formatNumber(row.qps) }}</div><div>未分配分片 {{ row.unassigned_shards }}</div></template></el-table-column>
          <el-table-column v-if="canManageMiddleware" label="操作" width="180" fixed="right"><template #default="{ row }"><el-button link type="warning" :loading="isActing('elasticsearch', row.id, 'reroute')" @click="handleAction('elasticsearch', row.id, 'reroute')">Reroute</el-button><el-button link type="primary" :loading="isActing('elasticsearch', row.id, 'rollover')" @click="handleAction('elasticsearch', row.id, 'rollover')">Rollover</el-button></template></el-table-column>
        </el-table>
      </el-card>

      <el-card v-if="activeTab === 'instances'" shadow="never" class="section-card">
        <template #header><div class="section-title">节点管理</div></template>
        <el-table :data="filteredEsNodes" stripe style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="节点" min-width="150" />
          <el-table-column prop="cluster" label="集群" min-width="120" />
          <el-table-column prop="role" label="角色" min-width="140" />
          <el-table-column prop="endpoint" label="地址" min-width="170" />
          <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'online' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column label="资源" min-width="170"><template #default="{ row }"><div>Heap {{ row.heap_usage }}%</div><div>CPU {{ row.cpu_usage }}% / 磁盘 {{ row.disk_usage }}%</div></template></el-table-column>
          <el-table-column v-if="canManageMiddleware" label="操作" width="120" fixed="right"><template #default="{ row }"><el-button link type="primary" :loading="isActing('elasticsearch', row.id, 'restart_node')" @click="handleAction('elasticsearch', row.id, 'restart_node')">重启节点</el-button></template></el-table-column>
        </el-table>
      </el-card>

      <div v-if="activeTab === 'runtime'" class="stack-grid">
        <div class="dual-grid">
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">索引状态</div></template>
            <el-table :data="filteredEsIndices" stripe style="width: 100%" v-loading="loading">
              <el-table-column prop="name" label="索引" min-width="220" />
              <el-table-column prop="cluster" label="集群" min-width="110" />
              <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag :type="healthTagType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
              <el-table-column prop="docs" label="文档数" width="100" />
              <el-table-column prop="size" label="大小" width="100" />
              <el-table-column prop="lifecycle" label="生命周期" width="100" />
            </el-table>
          </el-card>
          <el-card shadow="never" class="section-card">
            <template #header><div class="section-title">后台任务</div></template>
            <el-table :data="filteredEsTasks" stripe style="width: 100%" v-loading="loading">
              <el-table-column prop="name" label="任务" min-width="160" />
              <el-table-column prop="cluster" label="集群" min-width="110" />
              <el-table-column prop="progress" label="进度" width="160"><template #default="{ row }"><el-progress :percentage="row.progress" :status="taskProgressStatus(row.status)" :stroke-width="8" /></template></el-table-column>
              <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="taskTagType(row.status)" size="small">{{ row.status }}</el-tag></template></el-table-column>
            </el-table>
          </el-card>
        </div>
        <el-card shadow="never" class="section-card">
          <template #header><div class="section-title">运行事件</div></template>
          <div class="timeline-list">
            <div v-for="event in elasticsearch.events || []" :key="event.id" class="timeline-item"><div class="timeline-dot" :class="`timeline-dot--${event.level}`"></div><div class="timeline-content"><div class="timeline-top"><span class="timeline-title">{{ event.title }}</span><span class="timeline-time">{{ event.time }}</span></div><div class="timeline-detail">{{ event.detail }}</div></div></div>
          </div>
        </el-card>
      </div>
    </template>

    <el-dialog v-model="clusterDialogVisible" :title="`新增${moduleMeta.title.replace(' 管理', '')}集群`" width="560px" append-to-body destroy-on-close>
      <el-form :model="clusterForm" label-width="110px">
        <el-form-item label="集群名称" required><el-input v-model="clusterForm.name" placeholder="请输入集群名称" /></el-form-item>
        <el-form-item label="环境"><el-select v-model="clusterForm.environment" style="width:100%"><el-option label="prod" value="prod" /><el-option label="test" value="test" /><el-option label="dev" value="dev" /></el-select></el-form-item>
        <template v-if="moduleKey === 'redis'"><el-form-item label="模式"><el-select v-model="clusterForm.mode" style="width:100%"><el-option label="Redis Cluster" value="Redis Cluster" /><el-option label="Sentinel" value="Sentinel" /><el-option label="Master / Replica" value="Master / Replica" /></el-select></el-form-item><el-form-item label="内存容量"><el-input-number v-model="clusterForm.memory_total_gb" :min="1" style="width:100%" /></el-form-item><el-form-item label="命中率"><el-input-number v-model="clusterForm.hit_rate" :min="1" :max="100" :precision="1" style="width:100%" /></el-form-item></template>
        <template v-else-if="moduleKey === 'rocketmq'"><el-form-item label="NameServer"><el-input-number v-model="clusterForm.nameserver_count" :min="1" style="width:100%" /></el-form-item><el-form-item label="目标 TPS"><el-input-number v-model="clusterForm.tps" :min="0" style="width:100%" /></el-form-item><el-form-item label="Topic 数"><el-input-number v-model="clusterForm.topic_count" :min="0" style="width:100%" /></el-form-item></template>
        <template v-else><el-form-item label="存储规模"><el-input v-model="clusterForm.storage" placeholder="例如 1.2TB" /></el-form-item><el-form-item label="目标 QPS"><el-input-number v-model="clusterForm.qps" :min="0" style="width:100%" /></el-form-item></template>
      </el-form>
      <template #footer><el-button @click="clusterDialogVisible = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitCluster">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="instanceDialogVisible" :title="instanceDialogTitle" width="560px" append-to-body destroy-on-close>
      <el-form :model="instanceForm" label-width="110px">
        <el-form-item label="所属集群" required><el-select v-model="instanceForm.cluster" style="width:100%"><el-option v-for="item in clusterOptions" :key="item.name" :label="item.name" :value="item.name" /></el-select></el-form-item>
        <el-form-item :label="instanceNameLabel" required><el-input v-model="instanceForm.name" placeholder="请输入名称" /></el-form-item>
        <el-form-item label="环境"><el-select v-model="instanceForm.environment" style="width:100%"><el-option label="prod" value="prod" /><el-option label="test" value="test" /><el-option label="dev" value="dev" /></el-select></el-form-item>
        <el-form-item :label="roleLabel"><el-input v-model="instanceForm.role" placeholder="请输入角色" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="instanceForm.endpoint" placeholder="IP:Port" /></el-form-item>
        <template v-if="moduleKey === 'redis'"><el-form-item label="版本"><el-input v-model="instanceForm.version" /></el-form-item><el-form-item label="QPS"><el-input-number v-model="instanceForm.qps" :min="0" style="width:100%" /></el-form-item><el-form-item label="连接数"><el-input-number v-model="instanceForm.connections" :min="0" style="width:100%" /></el-form-item><el-form-item label="持久化"><el-input v-model="instanceForm.persistence" /></el-form-item></template>
        <template v-else-if="moduleKey === 'rocketmq'"><el-form-item label="版本"><el-input v-model="instanceForm.version" /></el-form-item><el-form-item label="TPS"><el-input-number v-model="instanceForm.tps" :min="0" style="width:100%" /></el-form-item><el-form-item label="Topic 数"><el-input-number v-model="instanceForm.topic_count" :min="0" style="width:100%" /></el-form-item><el-form-item label="磁盘使用率"><el-input-number v-model="instanceForm.disk_usage" :min="0" :max="100" style="width:100%" /></el-form-item><el-form-item label="消费积压"><el-input-number v-model="instanceForm.consumer_lag" :min="0" style="width:100%" /></el-form-item></template>
        <template v-else><el-form-item label="状态"><el-select v-model="instanceForm.status" style="width:100%"><el-option label="online" value="online" /><el-option label="offline" value="offline" /></el-select></el-form-item><el-form-item label="Heap"><el-input-number v-model="instanceForm.heap_usage" :min="0" :max="100" style="width:100%" /></el-form-item><el-form-item label="CPU"><el-input-number v-model="instanceForm.cpu_usage" :min="0" :max="100" style="width:100%" /></el-form-item><el-form-item label="磁盘"><el-input-number v-model="instanceForm.disk_usage" :min="0" :max="100" style="width:100%" /></el-form-item></template>
      </el-form>
      <template #footer><el-button @click="instanceDialogVisible = false">取消</el-button><el-button type="primary" :loading="submitting" @click="submitInstance">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { RefreshRight, Grid, Monitor, Histogram, Plus } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { getMiddlewareOverview, runMiddlewareAction } from '@/api/modules/middleware'

const route = useRoute()
const authStore = useAuthStore()
const loading = ref(false)
const submitting = ref(false)
const actingKey = ref('')
const activeTab = ref('clusters')
const filters = ref({ search: '', environment: 'all', state: 'all' })
const payload = ref(createDefaultPayload())
const clusterDialogVisible = ref(false)
const instanceDialogVisible = ref(false)
const clusterForm = ref(createClusterForm())
const instanceForm = ref(createInstanceForm())
const TAB_STORAGE_PREFIX = 'middleware-active-tab-'

const MODULE_META = {
  redis: { badge: 'Middleware / Redis', title: 'Redis 管理', subtitle: '查看集群、实例、热点 Key 与复制状态的演示数据。', bannerTitle: '缓存高可用与热点治理', bannerDesc: '聚焦复制延迟、热点 Key 和主从切换场景。' },
  rocketmq: { badge: 'Middleware / RocketMQ', title: 'RocketMQ 管理', subtitle: '查看 Broker、消费组积压与 Topic 演示数据。', bannerTitle: '消息链路与积压处理', bannerDesc: '聚焦 Broker 负载、消费积压和 Rebalance 演示。' },
  elasticsearch: { badge: 'Middleware / Elasticsearch', title: 'Elasticsearch 管理', subtitle: '查看集群健康度、节点负载、索引和任务演示数据。', bannerTitle: '检索集群健康治理', bannerDesc: '聚焦未分配分片、节点负载和索引 rollover。' },
}

function createDefaultPayload() {
  return {
    updated_at: '', overview: { modules: [] },
    redis: { summary: {}, alerts: [], clusters: [], instances: [], hot_keys: [], events: [] },
    rocketmq: { summary: {}, alerts: [], clusters: [], brokers: [], consumer_groups: [], topics: [], events: [] },
    elasticsearch: { summary: {}, alerts: [], clusters: [], nodes: [], indices: [], tasks: [], events: [] },
  }
}
function createClusterForm() { return { name: '', environment: 'test', mode: 'Redis Cluster', memory_total_gb: 32, hit_rate: 98.6, nameserver_count: 2, tps: 0, topic_count: 0, storage: '1.2TB', qps: 0 } }
function createInstanceForm() { return { cluster: '', name: '', environment: 'test', role: 'master', endpoint: '', version: '', qps: 1200, connections: 96, persistence: 'AOF', tps: 900, topic_count: 16, disk_usage: 42, consumer_lag: 0, status: 'online', heap_usage: 36, cpu_usage: 22 } }

const moduleKey = computed(() => route.meta.moduleKey || 'redis')
const moduleMeta = computed(() => MODULE_META[moduleKey.value] || MODULE_META.redis)
const redis = computed(() => payload.value.redis)
const rocketmq = computed(() => payload.value.rocketmq)
const elasticsearch = computed(() => payload.value.elasticsearch)
const currentModule = computed(() => payload.value[moduleKey.value] || {})
const currentAlerts = computed(() => currentModule.value.alerts || [])
const moduleStatus = computed(() => currentModule.value.summary?.module_status || 'healthy')
const moduleStatusLabel = computed(() => ({ healthy: '健康', warning: '告警', critical: '风险' }[moduleStatus.value] || moduleStatus.value))
const formattedUpdatedAt = computed(() => String(payload.value.updated_at || '--').replace('T', ' ').slice(0, 16))
const canManageMiddleware = computed(() => authStore.hasPermission('ops.middleware.manage'))
const mainTabs = computed(() => [{ key: 'clusters', label: '集群管理', icon: Grid }, { key: 'instances', label: moduleKey.value === 'rocketmq' ? 'Broker 管理' : moduleKey.value === 'elasticsearch' ? '节点管理' : '实例管理', icon: Monitor }, { key: 'runtime', label: '运行视图', icon: Histogram }])
const searchPlaceholder = computed(() => {
  const mapping = {
    redis: { clusters: '搜索集群 / 模式', instances: '搜索实例 / 集群 / 地址', runtime: '搜索热点 Key / 集群 / 风险' },
    rocketmq: { clusters: '搜索集群 / 环境', instances: '搜索 Broker / 集群 / 地址', runtime: '搜索消费组 / Topic / 集群' },
    elasticsearch: { clusters: '搜索集群 / 存储', instances: '搜索节点 / 集群 / 地址', runtime: '搜索索引 / 任务 / 集群' },
  }
  return mapping[moduleKey.value][activeTab.value]
})
const instanceButtonLabel = computed(() => moduleKey.value === 'rocketmq' ? '新增 Broker' : moduleKey.value === 'elasticsearch' ? '新增节点' : '新增实例')
const instanceDialogTitle = computed(() => moduleKey.value === 'rocketmq' ? '新增 Broker' : moduleKey.value === 'elasticsearch' ? '新增节点' : '新增 Redis 实例')
const instanceNameLabel = computed(() => moduleKey.value === 'rocketmq' ? 'Broker 名称' : moduleKey.value === 'elasticsearch' ? '节点名称' : '实例名称')
const roleLabel = computed(() => moduleKey.value === 'elasticsearch' ? '节点角色' : '角色')
const clusterOptions = computed(() => currentModule.value.clusters || [])

const environmentOptions = computed(() => {
  const values = []
  const push = value => { if (value && !values.includes(value)) values.push(value) }
  ;(currentModule.value.clusters || []).forEach(item => push(item.environment))
  ;(currentModule.value.instances || []).forEach(item => push(item.environment))
  ;(currentModule.value.brokers || []).forEach(item => push(item.environment))
  ;(currentModule.value.nodes || []).forEach(item => push(clusterEnvironment(item.cluster)))
  return values
})
const stateOptions = computed(() => moduleKey.value === 'elasticsearch' ? [{ label: '全部健康度', value: 'all' }, { label: 'green', value: 'green' }, { label: 'yellow', value: 'yellow' }, { label: 'red', value: 'red' }] : [{ label: '全部状态', value: 'all' }, { label: 'healthy', value: 'healthy' }, { label: 'warning', value: 'warning' }])
const summaryCards = computed(() => moduleKey.value === 'redis' ? [{ label: '集群数', value: redis.value.summary.cluster_count || 0, meta: '缓存集群' }, { label: '实例数', value: redis.value.summary.instance_count || 0, meta: '实例节点' }, { label: '峰值 QPS', value: formatNumber(redis.value.summary.peak_qps), meta: '当前演示峰值' }, { label: '热点 Key', value: redis.value.summary.hot_key_count || 0, meta: '待治理项' }] : moduleKey.value === 'rocketmq' ? [{ label: '集群数', value: rocketmq.value.summary.cluster_count || 0, meta: '消息集群' }, { label: 'Broker 数', value: rocketmq.value.summary.broker_count || 0, meta: '节点规模' }, { label: '峰值 TPS', value: formatNumber(rocketmq.value.summary.peak_tps), meta: '当前演示峰值' }, { label: 'Topic 数', value: rocketmq.value.summary.topic_count || 0, meta: '业务 Topic' }] : [{ label: '集群数', value: elasticsearch.value.summary.cluster_count || 0, meta: '检索集群' }, { label: '节点数', value: elasticsearch.value.summary.node_count || 0, meta: '数据节点' }, { label: '峰值 QPS', value: formatNumber(elasticsearch.value.summary.peak_qps), meta: '当前查询峰值' }, { label: '索引数', value: elasticsearch.value.summary.index_count || 0, meta: '索引规模' }])

const filteredRedisClusters = computed(() => applyCommonFilter(redis.value.clusters || [], item => [item.name, item.mode], item => item.status, item => item.environment))
const filteredRedisInstances = computed(() => applyCommonFilter(redis.value.instances || [], item => [item.name, item.cluster, item.endpoint, item.role], item => item.status, item => item.environment))
const filteredRedisHotKeys = computed(() => applyCommonFilter(redis.value.hot_keys || [], item => [item.key, item.cluster, item.risk], () => 'all', item => clusterEnvironment(item.cluster)))
const filteredRocketmqClusters = computed(() => applyCommonFilter(rocketmq.value.clusters || [], item => [item.name], item => item.status, item => item.environment))
const filteredRocketmqBrokers = computed(() => applyCommonFilter(rocketmq.value.brokers || [], item => [item.name, item.cluster, item.endpoint, item.role], item => item.status, item => item.environment))
const filteredRocketmqGroups = computed(() => applyCommonFilter(rocketmq.value.consumer_groups || [], item => [item.group, item.topic, item.cluster], item => item.status, item => clusterEnvironment(item.cluster)))
const filteredRocketmqTopics = computed(() => applyCommonFilter(rocketmq.value.topics || [], item => [item.name, item.cluster], () => 'all', item => clusterEnvironment(item.cluster)))
const filteredEsClusters = computed(() => applyCommonFilter(elasticsearch.value.clusters || [], item => [item.name, item.storage], item => item.health, item => item.environment))
const filteredEsNodes = computed(() => applyCommonFilter(elasticsearch.value.nodes || [], item => [item.name, item.cluster, item.role, item.endpoint], () => 'all', item => clusterEnvironment(item.cluster)))
const filteredEsIndices = computed(() => applyCommonFilter(elasticsearch.value.indices || [], item => [item.name, item.cluster, item.lifecycle], item => item.status, item => clusterEnvironment(item.cluster)))
const filteredEsTasks = computed(() => applyCommonFilter(elasticsearch.value.tasks || [], item => [item.name, item.cluster, item.status], () => 'all', item => clusterEnvironment(item.cluster)))

function clusterEnvironment(clusterName) { const clusters = currentModule.value.clusters || []; return clusters.find(item => item.name === clusterName)?.environment || 'prod' }
function applyCommonFilter(items, fields, stateGetter, envGetter) { const keyword = String(filters.value.search || '').trim().toLowerCase(); return items.filter(item => (!keyword || fields(item).some(value => String(value || '').toLowerCase().includes(keyword))) && (filters.value.environment === 'all' || envGetter(item) === filters.value.environment) && (filters.value.state === 'all' || stateGetter(item) === filters.value.state)) }
function formatNumber(value) { if (value == null || value === '') return '--'; return Number(value).toLocaleString('zh-CN') }
function statusTagType(status) { return { healthy: 'success', online: 'success', warning: 'warning', critical: 'danger', error: 'danger' }[status] || 'info' }
function healthTagType(status) { return { green: 'success', yellow: 'warning', red: 'danger' }[status] || 'info' }
function riskTagType(risk) { return { high: 'danger', medium: 'warning', low: 'info' }[risk] || 'info' }
function taskTagType(status) { return { completed: 'success', running: 'warning', warning: 'danger' }[status] || 'info' }
function taskProgressStatus(status) { return status === 'warning' ? 'exception' : status === 'completed' ? 'success' : '' }
function summaryAlertTagType(level) { return { warning: 'warning', danger: 'danger', success: 'success' }[level] || 'info' }
function compactAlertMessage(message) { const text = String(message || '').trim(); return text.length <= 24 ? text : `${text.slice(0, 24)}...` }
function isActing(module, targetId, action) { return actingKey.value === `${module}:${targetId}:${action}` }
function switchTab(tabKey) { activeTab.value = tabKey; resetFilters(); localStorage.setItem(`${TAB_STORAGE_PREFIX}${moduleKey.value}`, tabKey) }
function resetFilters() { filters.value = { search: '', environment: 'all', state: 'all' } }
function openClusterDialog() { clusterForm.value = createClusterForm(); clusterDialogVisible.value = true }
function openInstanceDialog() {
  instanceForm.value = createInstanceForm()
  instanceForm.value.cluster = clusterOptions.value[0]?.name || ''
  if (moduleKey.value === 'rocketmq') instanceForm.value.role = 'master'
  if (moduleKey.value === 'elasticsearch') instanceForm.value.role = 'data_hot,ingest'
  if (moduleKey.value === 'elasticsearch') instanceForm.value.endpoint = '127.0.0.1:9200'
  if (moduleKey.value === 'rocketmq') instanceForm.value.endpoint = '127.0.0.1:10911'
  if (moduleKey.value === 'redis') instanceForm.value.endpoint = '127.0.0.1:6379'
  instanceDialogVisible.value = true
}

async function refreshData() {
  loading.value = true
  try {
    payload.value = await getMiddlewareOverview()
  } finally {
    loading.value = false
  }
}

async function handleAction(module, targetId, action) {
  actingKey.value = `${module}:${targetId}:${action}`
  try {
    const response = await runMiddlewareAction(module, targetId, action)
    payload.value = response.data
    ElMessage.success(response.message || '操作成功')
  } finally {
    actingKey.value = ''
  }
}

async function submitCluster() {
  submitting.value = true
  try {
    const response = await runMiddlewareAction(moduleKey.value, '', 'create_cluster', clusterForm.value)
    payload.value = response.data
    clusterDialogVisible.value = false
    ElMessage.success(response.message || '新增集群成功')
  } finally {
    submitting.value = false
  }
}

async function submitInstance() {
  submitting.value = true
  try {
    const response = await runMiddlewareAction(moduleKey.value, '', 'create_instance', instanceForm.value)
    payload.value = response.data
    instanceDialogVisible.value = false
    ElMessage.success(response.message || '新增实例成功')
  } finally {
    submitting.value = false
  }
}

watch(moduleKey, () => {
  const storedTab = localStorage.getItem(`${TAB_STORAGE_PREFIX}${moduleKey.value}`)
  activeTab.value = ['clusters', 'instances', 'runtime'].includes(storedTab) ? storedTab : 'clusters'
  actingKey.value = ''
  resetFilters()
}, { immediate: true })

onMounted(refreshData)
</script>

<style scoped>
.middleware-page { --module-primary: #2563eb; --module-soft: rgba(37, 99, 235, 0.08); }
.middleware-page--redis { --module-primary: #10b981; --module-soft: rgba(16, 185, 129, 0.1); }
.middleware-page--rocketmq { --module-primary: #f97316; --module-soft: rgba(249, 115, 22, 0.1); }
.middleware-page--elasticsearch { --module-primary: #7c3aed; --module-soft: rgba(124, 58, 237, 0.1); }
.middleware-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.module-badge { display: inline-flex; margin-bottom: 10px; padding: 4px 10px; border-radius: 999px; color: var(--module-primary); background: var(--module-soft); font-size: 12px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
.page-subtitle { margin: 6px 0 0; color: var(--text-secondary); font-size: 13px; }
.header-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.module-banner { margin-bottom: 16px; padding: 18px 20px; border-radius: 18px; border: 1px solid color-mix(in srgb, var(--module-primary) 18%, white); background: linear-gradient(135deg, var(--module-soft), rgba(255,255,255,.96)); }
.module-banner__title { color: var(--module-primary); font-size: 16px; font-weight: 700; }
.module-banner__desc { margin-top: 6px; color: var(--text-secondary); font-size: 13px; }
.middleware-alert-strip { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; padding: 10px 12px; border-radius: 12px; background: rgba(248,250,252,.88); border: 1px solid rgba(148,163,184,.18); }
.middleware-alert-strip__label { font-size: 12px; font-weight: 700; color: #475569; }
.middleware-alert-strip__tag { max-width: 280px; overflow: hidden; text-overflow: ellipsis; }
.alert-popover { display: flex; flex-direction: column; gap: 8px; }
.alert-popover__item { display: flex; gap: 8px; align-items: flex-start; color: #334155; line-height: 1.5; }
.module-summary-grid, .dual-grid { display: grid; gap: 16px; margin-bottom: 16px; }
.stack-grid { display: grid; gap: 16px; }
.module-summary-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.dual-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.module-summary-card { padding: 18px 20px; border-radius: 16px; border: 1px solid color-mix(in srgb, var(--module-primary) 18%, white); background: linear-gradient(135deg, var(--module-soft), rgba(255,255,255,.96)); box-shadow: 0 10px 30px rgba(15,23,42,.06); }
.module-summary-label, .module-summary-meta { display: block; color: var(--text-secondary); font-size: 12px; }
.module-summary-card strong { display: block; margin: 10px 0 8px; font-size: 28px; line-height: 1; color: var(--text-primary); }
.middleware-tabs { margin-bottom: 16px; }
.toolbar-card { margin-bottom: 16px; }
.toolbar-grid { display: grid; grid-template-columns: 2fr 1fr 1fr auto; gap: 12px; align-items: center; }
.toolbar-control { width: 100%; }
.toolbar-actions { display: flex; justify-content: flex-end; }
.section-card { margin-bottom: 16px; border-radius: 16px; }
.section-title { font-weight: 700; color: var(--text-primary); }
.timeline-list { display: flex; flex-direction: column; gap: 14px; }
.timeline-item { display: flex; gap: 12px; align-items: flex-start; }
.timeline-dot { width: 10px; height: 10px; margin-top: 7px; border-radius: 50%; background: #94a3b8; box-shadow: 0 0 0 4px rgba(148,163,184,.12); }
.timeline-dot--info { background: var(--module-primary); box-shadow: 0 0 0 4px color-mix(in srgb, var(--module-primary) 18%, white); }
.timeline-dot--warning { background: #f59e0b; box-shadow: 0 0 0 4px rgba(245,158,11,.16); }
.timeline-content { flex: 1; min-width: 0; padding-bottom: 10px; border-bottom: 1px dashed rgba(148,163,184,.24); }
.timeline-top { display: flex; justify-content: space-between; gap: 12px; }
.timeline-title { color: var(--text-primary); font-weight: 700; }
.timeline-time { color: var(--text-secondary); font-size: 12px; white-space: nowrap; }
.timeline-detail { margin-top: 6px; color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.warning-text { color: #d97706; font-weight: 700; }
@media (max-width: 1024px) { .module-summary-grid, .dual-grid, .toolbar-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 768px) { .middleware-header, .timeline-top { flex-direction: column; } .header-actions { width: 100%; } .module-summary-grid, .dual-grid, .toolbar-grid { grid-template-columns: 1fr; } .toolbar-actions { justify-content: flex-start; } }
</style>
