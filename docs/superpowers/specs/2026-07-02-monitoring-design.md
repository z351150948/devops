# 规格说明：监控扩展（主机 + 数据库）— B 轮二次开发

| 项 | 值 |
| --- | --- |
| 编号 | B-2026-07-02-01 |
| 日期 | 2026-07-02 |
| 状态 | 已评审，待规格审查 |
| 范围 | 主机监控 + 数据库监控（被动拉取 + 现有前端 tab 升级） |
| 配套 | A 轮 L1 rebrand（`bba4fe7` on `main` / `test`）已建立 Autotoll DevOps 品牌基线 |

## 1. 目标与背景

仓库当前可观测性域（`ops/observability_views.py`）含指标 / 日志 / Trace 三大数据源 ViewSet + K8s 集群管理（`ops/k8s_views.py`）+ Docker 主机管理（`ops/docker_views.py`）。运维现场最常用的「主机层 + 数据库层」监控能力在现有代码中**仅以 K8s node 指标 + SQL 工单数据源**形式存在，**没有独立的非容器主机监控 + 通用数据库监控**入口。

本 spec 填补：
1. **主机监控** — 基于 `ops.Host` 表（已有 SSH 凭据）做 on-demand 拉取 CPU / Mem / Disk / 网络指标，覆盖非 K8s 节点
2. **数据库监控** — 基于 `sqlaudit.DataSource` 表（已有 DB 凭据）做 on-demand 拉取连接 / QPS / 缓存 / 复制等指标，覆盖 MySQL 8 + Redis 7 + MongoDB

A 轮 rebrand 后仓库进入稳定的 Autotoll DevOps 品牌基线，本 spec 直接基于该基线扩展。

## 2. 范围

### 2.1 必须新增

| 项 | 路径 / 文件 | 备注 |
| --- | --- | --- |
| 后端 monitoring app 骨架 | `backend/monitoring/__init__.py`、`apps.py`、`urls.py` | Django app 注册在 `INSTALLED_APPS` 末尾 |
| 后端 models（仅运维元数据，不存历史指标） | `backend/monitoring/models.py` | 当前仅 `class ProbeAudit(models.Model)`（最近一次采集成功/失败时间 + host_id + db_id，**不入 EventWall** 写审计） |
| 后端 serializers | `backend/monitoring/serializers.py` | `HostProbeRequestSerializer`、`HostProbeResultSerializer`、`DatabaseProbeResultSerializer` |
| 后端 services（采集层） | `backend/monitoring/services/__init__.py` + 4 个子模块 | `host_probe.py` / `mysql_probe.py` / `redis_probe.py` / `mongo_probe.py` |
| 后端 API | `backend/monitoring/api.py` | 4 个 endpoint：批量 host probe、单机 host probe、批量 DB probe、单机 DB probe |
| 后端 RBAC 权限码 | `backend/rbac/registry.py` | 新增 2 个权限码：`monitoring.host.view` + `monitoring.database.view` |
| 后端 BUILTIN_ROLES 更新 | `backend/rbac/registry.py` | `ops-admin` 加 2 个权限；`platform-admin` 自动含（`'*'` 通配） |
| 前端 API 模块 | `frontend/src/api/modules/monitoring.js` | host probe / database probe 两个 API 包装 |
| 前端 K8sManage.vue 加 tab | `frontend/src/views/K8sManage.vue` | 新增「主机」tab + 4 stat card + host 列表（参照现有 cluster / node / namespace tab 模式） |
| 前端 ContainerManage.vue 加 tab | `frontend/src/views/ContainerManage.vue` | 新增「数据库」tab + 4 stat card + db 列表 |
| 前端路由不需要新增 | `frontend/src/router/index.js` | tab 在 K8sManage/ContainerManage 内部切换，**不**新增路由 |
| 测试 | `backend/monitoring/tests/test_host_probe.py` + 3 个 DB probe 测试 + RBAC 集成测试 | mock paramiko / pymysql / redis-py / pymongo，验证正常 / 异常 / 超时路径 |

### 2.2 严格不改（L1 + 二次开发工作流规约外）

| 项 | 保留形式 | 原因 |
| --- | --- | --- |
| Python 包名 | `backend/sxdevops/` 整目录 | A 轮 L1 不动项 |
| `INSTALLED_APPS` 顺序 | 在末尾追加 `'monitoring'`，不动既有 | Django app 注册惯例 |
| `ops.Host` 模型 | 不加字段（含 `ssh_password` 明文） | A 轮 L1 + Sqlaudit 原本 L1 不动加密层；B 轮保持 |
| `sqlaudit.DataSource` 模型 | 不加字段 | 同上 |
| `ops/observability_views.py` 现有 ViewSet | 不重构 | B 轮走新独立 monitoring app，避耦合 |
| `K8sManage.vue` 现有 8 个 tab | 不重构 | 在尾部追加「主机」tab，复用 `summaryCards = computed()` + `mainTabs` 模式 |
| `ContainerManage.vue` 现有 3 个 tab | 不重构 | 在尾部追加「数据库」tab |
| 前端路由 | 不新增 | tab 在工作台内部切换 |
| 历史指标存储（`metrics_*_history` 表） | **不建**（决策 1 被动拉取） | YAGNI，下一 phase |
| 定时后台采集（Celery / APScheduler） | **不做**（决策 1 被动拉取） | YAGNI |
| 告警阈值 + 通知 | **不做** | YAGNI，留 TODO 给 D 轮（监控告警） |
| AIOps action 联动 | **不做** | C 轮做，B 轮只暴露 REST API |
| 加密 SSH password / DB credentials | **不做** | L1 + Sqlaudit 原本 L1 不动加密层 |
| 现有 `scripts/rebrand/*` + verify_rebrand | 不改 | A 轮已闭环 |

### 2.3 不在本 spec 范围

- Docker / K8s node 内部指标（已有 `ops/k8s_views.py` + `ops/docker_views.py` 处理）
- 应用层 APM 指标（业务自定义 metrics）
- 日志 / Trace 数据源扩展（`ops/log_views.py` + `ops/observability_views.py` TracingDataSourceViewSet 已有）
- 自愈 / 巡检（AIOps / C 轮范围）

## 3. 决策点（执行前用户已确认）

| ID | 决策点 | 用户选择 | 备注 |
| --- | --- | --- | --- |
| D-1 | 监控数据采集策略 | **被动拉取**（按需调用，主管页面加载时拉 + 手动 refresh + test_connection 联调） | 最少代码、最稳 |
| D-2 | 数据库支持范围 | **MySQL 8 + MongoDB（D-2b 降级）** | 决策变体 D-2b：plan 任务 1 探测后发现 `sqlaudit.DataSource.db_type` choices 不含 `redis`（仅 `mysql/mongodb/polardb`），且无 `connection_params` JSONField（flat schema）。受保护路径禁止改 sqlaudit 模型，因此放弃 Redis 路径，仅 MySQL 8 + MongoDB |
| D-3 | 后端集成位置 | **独立 `monitoring/` app** | 借鉴 cmdb / aiops 独立 app 模式 |
| D-4 | 前端工作台 | **与 K8sManage.vue / ContainerManage.vue 同级进化**（在两页内部分别加 tab + stat card） | 不开新路由，复用现有 hero/tabs 模板 |

> ✅ **D-2 已落地为 D-2b**：plan 任务 1 探测 + 用户决策，放弃 Redis 路径。spec § 3 决策点 D-2 改为「MySQL 8 + MongoDB」。后续 plan 任务 6 写 `redis_probe.py` 占位 stub（测试 skip），任务 8 `api.py` 不再分发 `redis` 分支，任务 12 ContainerManage 数据库 tab 表格不显示 Redis 列。

## 4. 架构

```
┌──────────────┐   ┌─────────────────────┐
│ K8sManage.vue│   │ ContainerManage.vue │
│ + 主机 tab   │   │ + 数据库 tab         │  ← 前端复用现有 hero + 4 stat + tabs
└──────┬───────┘   └──────────┬──────────┘
       │ On-demand            │ On-demand
       ▼                      ▼
┌──────────────────────────────┐
│ monitoring/api.py             │  ← 新建独立 monitoring/ app
│ - HostProbeViewSet (pull)    │
│ - DatabaseProbeViewSet (pull) │
└──────┬───────────────────────┘
       │ Service layer (按需调)
       ▼
┌──────────────────────────────────┐
│ monitoring/services/             │
│ ├─ host_probe.py   (paramiko)    │  ← SSH "5 步走" 模板
│ ├─ mysql_probe.py  (pymysql)     │
│ ├─ redis_probe.py  (redis-py)    │
│ └─ mongo_probe.py  (pymongo)     │
└──────────────────────────────────┘
       │ On-demand
       ▼
┌──────────────────────────────────┐
│ 现有 cmdb.ops.Host (SSH 凭据)     │  ← **不新建**数据源表，复用已有
│ 现有 sqlaudit.DataSource (DB 配置) │
└──────────────────────────────────┘
```

## 5. 数据模型

### 5.1 新增 model（仅运维元数据）

```python
# backend/monitoring/models.py
from django.db import models

class ProbeAudit(models.Model):
    """最近一次采集成功/失败时间（不存历史指标，决策 1）。"""

    TARGET_HOST = 'host'
    TARGET_DATABASE = 'database'
    TARGET_KIND_CHOICES = [(TARGET_HOST, '主机'), (TARGET_DATABASE, '数据库')]

    target_kind = models.CharField('目标类型', max_length=16, choices=TARGET_KIND_CHOICES)
    target_id = models.IntegerField('目标 ID（ops.Host.id 或 sqlaudit.DataSource.id）')
    last_status = models.CharField('最近状态', max_length=16)  # 'ok' / 'error' / 'timeout' / 'misconfigured'
    last_error = models.TextField('最近错误', blank=True, default='')
    last_duration_ms = models.IntegerField('最近耗时 ms', default=0)
    last_collected_at = models.DateTimeField('最近采集时间', auto_now=True)

    class Meta:
        unique_together = ('target_kind', 'target_id')
        indexes = [models.Index(fields=['target_kind', 'last_collected_at'])]
```

### 5.2 复用 model

- `ops.Host`（`backend/ops/models.py:15-51`）— 主机列表，含 `ip_address / ssh_port / ssh_user / ssh_password`
- `sqlaudit.DataSource`（`backend/sqlaudit/models.py`）— **MySQL / MongoDB 数据库连接**（D-2b 限制）
  - 实际 schema 是 **flat**：`name / db_type / host / port / user / password / charset / remark / is_active / created_at / updated_at`
  - **`db_type` choices** = `[('mysql', 'MySQL'), ('mongodb', 'MongoDB'), ('polardb', 'PolarDB')]` — **不含 `redis`**
  - **没有 `connection_params` JSONField** — 凭据就是 flat 字段本身
  - D-2b 决策下，B 轮 service 层用 flat 字段组装连接参数

## 6. API 接口

### 6.1 路由

`backend/monitoring/urls.py`：
```python
urlpatterns = [
    path('api/monitoring/hosts/probe/', views.HostProbeBulkView.as_view(), name='monitoring-hosts-probe-bulk'),
    path('api/monitoring/hosts/<int:host_id>/probe/', views.HostProbeSingleView.as_view(), name='monitoring-hosts-probe-single'),
    path('api/monitoring/databases/probe/', views.DatabaseProbeBulkView.as_view(), name='monitoring-databases-probe-bulk'),
    path('api/monitoring/databases/<int:ds_id>/probe/', views.DatabaseProbeSingleView.as_view(), name='monitoring-databases-probe-single'),
]
```

### 6.2 请求 / 响应

#### 6.2.1 批量主机 probe

- `POST /api/monitoring/hosts/probe/`
- 请求体：`{"ids": [1, 2, 3]}` 或 `{}`（空对象 = cmdb.Host 全表）
- 响应：
  ```json
  {
    "results": [
      {
        "id": 1, "hostname": "node-01", "ip": "10.10.30.100",
        "status": "ok", "duration_ms": 248,
        "metrics": {
          "cpu": {"usage_pct": 12.4, "load1": 0.32, "load5": 0.28, "load15": 0.31},
          "memory": {"total_mb": 16000, "used_mb": 4800, "usage_pct": 30.0},
          "disk": [{"mount": "/", "used_pct": 45, "size_gb": 100}],
          "network": {"rx_bytes": 1234567, "tx_bytes": 7654321},
          "uptime_seconds": 1234567
        },
        "error": null
      }
    ],
    "summary": {"total": 1, "ok": 1, "error": 0, "timeout": 0, "duration_ms": 248}
  }
  ```

#### 6.2.2 单机主机 probe

- `GET /api/monitoring/hosts/<host_id>/probe/`
- 响应：与单条 `results[]` 项同结构

#### 6.2.3 批量数据库 probe + 单库 probe

- 同样模式，MySQL / MongoDB 各自响应结构（D-2b 决策下，**无 Redis**）：
  - **MySQL**：`{"status", "duration_ms", "metrics": {"connections": N, "threads_connected": N, "questions": N, "slow_queries": N, "innodb_buffer_pool_hit_rate": 0.99, "replication": {"is_slave": bool, "seconds_behind_master": N}}, "error": null}`
  - **MongoDB**：`{"status", "duration_ms", "metrics": {"connections": {"current": N, "available": N}, "opcounters": {"insert": N, "query": N, "update": N, "delete": N, "command": N}, "wiredtiger": {"cache_used_mb": N, "cache_max_mb": N}, "replication": {"is_secondary": bool, "lag_seconds": N}}, "error": null}`
  - **PolarDB**（D-2b 不覆盖，仅记录）：PolarDB 是阿里云 MySQL 兼容数据库，可视作 MySQL 同源；sqlaudit 现有 choices 含 `polardb` 但 B 轮 service 仅支持 `mysql/mongodb`，polardb 走 mysql service 路径（pymysql 兼容）。

## 7. 前端集成

### 7.1 K8sManage.vue 新增「主机」tab

- 位置：在 `mainTabs` 数组末尾追加 `{ id: 'hosts-monitor', label: '主机', icon: 'Cpu' }`
- 触发：tab 切换时调用 `api.monitoring.probeHosts({ ids: [] })`
- 4 stat cards（按 tab 切换动态返回）：
  - 在管主机数 / 在线数 / 高 CPU 主机数（usage_pct >= 80）/ 平均 CPU 使用率
- 表格：hostname / IP / CPU% / Mem% / Disk% / 网络流量 / 状态 / 操作（"重试" button 触发 `probeHosts({ ids: [id] })`）
- 错误：单 host 失败时该行展示 `error` 字段，不影响其他行
- 不破坏现有 cluster / node / namespace / workload / pod / network / storage / config 8 个 tab

### 7.2 ContainerManage.vue 新增「数据库」tab

- 位置：在 `mainTabs` 数组末尾追加 `{ id: 'db-monitor', label: '数据库', icon: 'Coin' }`
- 触发：tab 切换时调用 `api.monitoring.probeDatabases({ ids: [] })`
- 4 stat cards：
  - 在管数据库数 / 连接中数 / 总 QPS（按库求和）/ 异常库数
- 表格：name / type / host:port / connections / QPS / cache / 状态 / 操作

### 7.3 API 模块

`frontend/src/api/modules/monitoring.js`：
```js
import request from '../request'

export const probeHosts = (payload) => request.post('/monitoring/hosts/probe/', payload)
export const probeHost = (id) => request.get(`/monitoring/hosts/${id}/probe/`)
export const probeDatabases = (payload) => request.post('/monitoring/databases/probe/', payload)
export const probeDatabase = (id) => request.get(`/monitoring/databases/${id}/probe/`)
```

## 8. 错误处理

| 场景 | 行为 |
| --- | --- |
| SSH 连接失败（paramiko AuthException / socket.error） | 单 host 返回 `status: error`，error 字段含 driver 错误；**不**中断其他 host |
| SSH 命令超时（>5s） | 该 host 返回 `status: timeout`；其他 host 继续 |
| DB 连接失败 | 单 DB 返回 status: error |
| 数据源未配齐凭据（缺 host / port / password） | 单 host/DB 返回 status: misconfigured + 提示字段名 |
| 大规模并发 | 顺序采集；超过 16 host 时分批（每批 8 并发，保留 8 worker 余量） |
| 后端 log 写 `ops.runtime.probe.{host,db}.err` | **不入 EventWall**（高频采集） |
| **不重试** | 仅前端手动 "重试" 按钮 + 单 host/DB probe endpoint |

## 9. RBAC

### 9.1 新增权限码

`backend/rbac/registry.py` `PERMISSION_DEFINITIONS` 追加：
```python
('monitoring.host.view', '查看主机监控', 'monitoring', '查看主机 CPU / 内存 / 磁盘 / 网络 on-demand 指标'),
('monitoring.database.view', '查看数据库监控', 'monitoring', '查看 MySQL / Redis / MongoDB on-demand 指标'),
```

### 9.2 BUILTIN_ROLES 更新

- `platform-admin`：自动含（`'*'` 通配）
- `ops-admin`：追加 `monitoring.host.view` + `monitoring.database.view`
- `developer` / `security-auditor` / `read-only`：不默认加；如需，按 B 轮 PR review 决定

## 10. 测试

| 文件 | 覆盖 |
| --- | --- |
| `backend/monitoring/tests/test_host_probe.py` | mock paramiko，验证 (a) 正常采集返回 / (b) AuthException 返回 status=error / (c) socket.timeout 返回 status=timeout / (d) 错配凭据返回 status=misconfigured |
| `backend/monitoring/tests/test_mysql_probe.py` | mock pymysql 连接，验证 `show global status` 解析 |
| `backend/monitoring/tests/test_redis_probe.py` | mock redis-py，验证 `info()` 解析（D-2b 降级时此文件改为 skip） |
| `backend/monitoring/tests/test_mongo_probe.py` | mock pymongo，验证 `serverStatus()` 解析 |
| `backend/monitoring/tests/test_api.py` | RBAC 集成测：用现有 RBAC helper，确保无权限返回 403 / 部分 host 失败不中断其他 host |

## 11. 验收标准

| 项 | 标准 | 验证方式 |
| --- | --- | --- |
| 后端测试 | `cd backend && python manage.py test monitoring` 全过 | pytest / manage.py test |
| 后端 API 可用 | 4 个 endpoint 返回结构符合 § 6.2 | curl / Postman |
| 前端构建 | `cd frontend && npm run build` 成功 | npm run build |
| K8sManage.vue 现有 8 个 tab 不破坏 | 视觉与功能回归 | 浏览器手测 |
| ContainerManage.vue 现有 3 个 tab 不破坏 | 视觉与功能回归 | 浏览器手测 |
| RBAC 权限码注册 | `monitoring.host.view` + `monitoring.database.view` 在 `rbac/registry.py` | grep |
| verify_rebrand.py 不破 | A 轮 verify 脚本 EXIT=0 | `python scripts/rebrand/verify_rebrand.py` |
| 受保护路径守住 | `ops.Host` `ssh_password` 字段保留；`sqlaudit.DataSource` 不动 | grep / git diff |
| 元文档自身 spec=13 / plan=31 不变 | `docs/superpowers/{specs,plans}/*` SxDevOps 计数 | grep |
| `INSTALLED_APPS` 末尾追加 `monitoring` | Django app 注册成功 | manage.py shell |
| L1 rebrand 资产完整 | `scripts/rebrand/sxdevops_to_autotoll.py` 与 `verify_rebrand.py` 不改 | git diff |
| 单 host 失败不中断批量 | 1 host 凭据错 + 1 host 正常，响应含 1 ok + 1 error | 集成测 |

## 12. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| ~~redis-py 不在 requirements.txt~~ | ✅ **已落地 D-2b**（plan 任务 1 探测 + 用户决策）：放弃 Redis，仅 MySQL + MongoDB。`sqlaudit.DataSource.db_type` 不含 `redis`，且无 `connection_params` JSONField；受保护路径禁止改 sqlaudit |
| cmdb.Host ssh_password 明文 | B 轮不引入加密层；spec § 13 留 hotfix TODO |
| 单 host 拉指标超时 | 5s 超时 + 单独 `status: timeout` 字段，不影响其他 host |
| sqlaudit.DataSource flat schema 字段缺失 | service 层按字段逐项检查，缺失字段返回 `misconfigured` 而非崩溃 |
| 后端并发过载 | 16 host / 8 并发分批；DB 顺序执行（MySQL/MongoDB 不并发） |
| 已启用 demo 账号写权限 | A 轮 `0022_disable_demo_provider_self_heal` 已禁 demo provider；B 轮 monitoring ViewSet 默认 `rbac_permissions` 即阻止 demo |

## 13. 后续 spec 引用

完成本 spec 后：

- **spec C**（知识库）会扩展 `monitoring.host.view` / `monitoring.database.view` 数据为 Agent 工具（新增 Action Handler `monitoring.host.query` / `monitoring.database.query`）
- **spec D**（监控告警 — 未来）会基于本 spec 的 `ProbeAudit` 表扩展阈值检测
- **加密凭据层**（未来）应单独 spec，跨 Host + DataSource + Cloud Credential 等所有 ssh_password 字段

## 14. 配套文档

- A 轮 L1 品牌重命名：[specs/2026-06-29-autotoll-rebrand-design.md](2026-06-29-autotoll-rebrand-design.md)
- 二次开发工作流：[docs/二次开发工作流.md](../../二次开发工作流.md)
- AIOps Action Handler 参考（[backend/aiops/action_handlers.py:149-201](D:\AI-worker\devops\backend\aiops\action_handlers.py#L149-L201)）
- 现有 K8sManage / ContainerManage 模板（[K8sManage.vue:3-25](D:\AI-worker\devops\frontend\src\views\K8sManage.vue#L3-L25) / [ContainerManage.vue:3-25](D:\AI-worker\devops\frontend\src\views\ContainerManage.vue#L3-L25)）
