# 截图目录说明

该目录用于存放 README 首页展示所需的产品截图。

## 当前文件

README 首页当前已接入 4 张真实页面截图：

- `dashboard.png`
- `cmdb.png`
- `logs-or-sql.png`
- `iac-orchestration.png`

同时补充了 1 张扩展展示截图：

- `k8s-pod-terminal.png`

这些 PNG 已按 README 展示场景做过统一高亮标注，更适合直接用于仓库首页导览。

最近一次已按本地演示环境刷新为 2026-03-27 的真实页面截图；其中 `cmdb.png` 已更新为新版 CMDB 的“主机管理 / 主机资产”视图，用于体现“主机管理并入 CMDB”后的统一资产治理入口；`logs-or-sql.png` 当前更偏向展示日志趋势图与查询结果区，便于直接体现排障链路；README 文案则同步覆盖 SQL 审计页内 Tab、多引擎（`MySQL` / `MongoDB` / `PolarDB`）与 RBAC 能力。

同时保留了同名 SVG 占位图，方便后续做示意图或临时替换：

- `dashboard.svg`
- `cmdb.svg`
- `logs-or-sql.svg`
- `iac-orchestration.svg`

## 推荐截图内容

### 1. dashboard.png

建议包含：
- 首页总览卡片
- 趋势图或统计图
- 告警或状态摘要

推荐说明文案：

> 平台首页总览：统一展示主机、部署、日志、告警等核心运维指标。

### 2. cmdb.png

建议包含：
- 业务资源树
- 主机管理或配置项管理列表
- 能体现统一资产治理的关系、成本或治理信息之一

推荐说明文案：

> CMDB 资产治理：通过统一资源树串联配置项、主机资产、主机申请与关系治理。

### 3. logs-or-sql.png

建议包含以下任一页面：
- 日志查询页
- SQL 审计页

推荐说明文案：

> 日志与审计：支持日志检索、SQL 审计与问题排查。

### 4. iac-orchestration.png

建议包含：
- 方案列表
- 方案设计
- 配置预览
- 执行与同步CMDB

推荐说明文案：

> IaC 资源编排：按模块设计云资源，生成 Terraform 配置并联动执行、同步 CMDB。

### 5. k8s-pod-terminal.png

建议包含：
- Pod Terminal 弹窗
- 终端连接状态
- 一条代表性的预置命令输出

推荐说明文案：

> K8s Pod Terminal：在浏览器内直接进入 Pod Shell，支持预置命令、会话日志导出与独立 RBAC 权限控制。

## 使用示例

后续如果你想更新 README 展示图，直接覆盖同名 `.png` 文件即可，根目录 `README.md` 无需额外修改。
